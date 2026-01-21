"""
前端服务 - 在 5002 端口提供前端页面和 API
"""
from flask import Flask, send_from_directory, request, jsonify, redirect
import os
import sys
import time
import secrets
from datetime import datetime
import pandas as pd
from urllib.parse import urlencode, urlparse, quote
import requests

# 导入 API 相关模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.service.review_service import ReviewService
from src.service.github_oauth_service import GitHubOAuthTokenStore
from src.service.app_settings import AppSettingsStore
from src.utils.log import logger

# 创建 Flask 应用
# 获取项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, 'web')
ui_app = Flask(__name__, static_folder=WEB_DIR, static_url_path='')
OAUTH_STATE_TTL_SECONDS = 600
oauth_state_store = {}
SETTINGS = AppSettingsStore()


def parse_github_repo_url(repo_url: str):
    if not repo_url:
        return None
    normalized = repo_url.strip()
    if normalized.startswith('git@'):
        normalized = normalized.replace(':', '/', 1)
        normalized = normalized.replace('git@', 'https://', 1)
    if normalized.startswith('ssh://'):
        normalized = normalized.replace('ssh://', 'https://', 1)
    parsed = urlparse(normalized)
    if parsed.netloc and parsed.netloc.lower() != 'github.com':
        return None
    path = parsed.path or normalized
    path = path.strip('/').replace('.git', '')
    if path.startswith('github.com/'):
        path = path[len('github.com/'):]
    if '/' not in path:
        return None
    owner, repo = path.split('/', 1)
    if not owner or not repo:
        return None
    return f"{owner}/{repo}"


def build_github_oauth_redirect(repo_full_name: str):
    client_id = os.getenv('GITHUB_OAUTH_CLIENT_ID') or SETTINGS.get('GITHUB_OAUTH_CLIENT_ID')
    callback_url = os.getenv('GITHUB_OAUTH_CALLBACK_URL') or SETTINGS.get('GITHUB_OAUTH_CALLBACK_URL')
    if not client_id:
        return None, "not_configured"
    if not callback_url:
        callback_url = request.url_root.rstrip('/') + '/oauth/github/callback'
    state = secrets.token_urlsafe(24)
    oauth_state_store[state] = {
        "repo_full_name": repo_full_name,
        "created_at": time.time()
    }
    query = urlencode({
        "client_id": client_id,
        "redirect_uri": callback_url,
        "scope": "repo,admin:repo_hook",
        "state": state
    })
    return f"https://github.com/login/oauth/authorize?{query}", None


def resolve_webhook_url():
    webhook_url = os.getenv('REVIEW_WEBHOOK_URL') or os.getenv('GITHUB_WEBHOOK_URL') or SETTINGS.get('REVIEW_WEBHOOK_URL')
    if webhook_url:
        return webhook_url.rstrip('/')
    parsed = urlparse(request.host_url)
    host = parsed.hostname
    port = parsed.port
    scheme = parsed.scheme
    target_port = 5001 if port == 5002 else port
    if target_port:
        netloc = f"{host}:{target_port}"
    else:
        netloc = host
    return f"{scheme}://{netloc}/review/webhook"


def exchange_github_token(code: str, redirect_uri: str):
    client_id = os.getenv('GITHUB_OAUTH_CLIENT_ID') or SETTINGS.get('GITHUB_OAUTH_CLIENT_ID')
    client_secret = os.getenv('GITHUB_OAUTH_CLIENT_SECRET') or SETTINGS.get('GITHUB_OAUTH_CLIENT_SECRET')
    if not client_id or not client_secret:
        return None, "not_configured"
    response = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri
        },
        timeout=15
    )
    if response.status_code >= 300:
        return None, "token_exchange_failed"
    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        return None, "token_exchange_failed"
    return access_token, None


def upsert_github_webhook(repo_full_name: str, access_token: str):
    github_api_base = os.getenv('GITHUB_URL') or 'https://api.github.com'
    github_api_base = github_api_base.rstrip('/')
    webhook_url = resolve_webhook_url()
    webhook_secret = os.getenv('GITHUB_WEBHOOK_SECRET')
    headers = {
        "Authorization": f"token {access_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    config = {
        "url": webhook_url,
        "content_type": "json",
        "insecure_ssl": "0"
    }
    if webhook_secret:
        config["secret"] = webhook_secret
    payload = {
        "name": "web",
        "active": True,
        "events": ["push", "pull_request"],
        "config": config
    }
    list_url = f"{github_api_base}/repos/{repo_full_name}/hooks"
    list_response = requests.get(list_url, headers=headers, timeout=15)
    if list_response.status_code >= 300:
        return False, f"Failed to list webhooks: {list_response.text}"
    existing_hooks = list_response.json()
    for hook in existing_hooks:
        if hook.get("config", {}).get("url") == webhook_url:
            hook_id = hook.get("id")
            update_url = f"{github_api_base}/repos/{repo_full_name}/hooks/{hook_id}"
            update_response = requests.patch(update_url, headers=headers, json=payload, timeout=15)
            if update_response.status_code >= 300:
                return False, f"Failed to update webhook: {update_response.text}"
            return True, "updated"
    create_response = requests.post(list_url, headers=headers, json=payload, timeout=15)
    if create_response.status_code >= 300:
        return False, f"Failed to create webhook: {create_response.text}"
    return True, "created"


def cleanup_oauth_state():
    now = time.time()
    expired = [state for state, entry in oauth_state_store.items()
               if now - entry.get("created_at", 0) > OAUTH_STATE_TTL_SECONDS]
    for state in expired:
        oauth_state_store.pop(state, None)

# API 路由
@ui_app.route('/api/review/logs', methods=['GET'])
def get_review_logs():
    """获取审查日志数据"""
    try:
        # 获取查询参数
        review_type = request.args.get('type', 'mr')  # 'mr' 或 'push'
        authors = request.args.getlist('authors') if request.args.get('authors') else None
        project_names = request.args.getlist('project_names') if request.args.get('project_names') else None
        
        # 时间范围
        updated_at_gte = request.args.get('updated_at_gte')
        updated_at_lte = request.args.get('updated_at_lte')
        
        if updated_at_gte:
            updated_at_gte = int(updated_at_gte)
        else:
            updated_at_gte = None
            
        if updated_at_lte:
            updated_at_lte = int(updated_at_lte)
        else:
            updated_at_lte = None
        
        # 根据类型获取数据
        if review_type == 'push':
            df = ReviewService().get_push_review_logs(
                authors=authors,
                project_names=project_names,
                updated_at_gte=updated_at_gte,
                updated_at_lte=updated_at_lte
            )
        else:
            df = ReviewService().get_mr_review_logs(
                authors=authors,
                project_names=project_names,
                updated_at_gte=updated_at_gte,
                updated_at_lte=updated_at_lte
            )
        
        # 转换数据格式
        if df.empty:
            return jsonify({
                'data': [],
                'total': 0,
                'average_score': 0
            })
        
        # 格式化时间戳
        if 'updated_at' in df.columns:
            df['updated_at'] = df['updated_at'].apply(
                lambda ts: datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                if isinstance(ts, (int, float)) else ts
            )
        
        # 格式化代码变更
        if 'additions' in df.columns and 'deletions' in df.columns:
            df['delta'] = df.apply(
                lambda row: f"+{int(row['additions'])}  -{int(row['deletions'])}"
                if not pd.isna(row['additions']) and not pd.isna(row['deletions'])
                else "",
                axis=1
            )
        
        # 转换为字典列表
        records = df.to_dict(orient='records')
        
        # 计算统计信息
        total = len(records)
        average_score = df['score'].mean() if 'score' in df.columns and not df.empty else 0
        
        return jsonify({
            'data': records,
            'total': total,
            'average_score': float(average_score) if not pd.isna(average_score) else 0
        })
    except Exception as e:
        logger.error(f"Failed to get review logs: {e}")
        return jsonify({'error': str(e)}), 500


@ui_app.route('/api/review/stats', methods=['GET'])
def get_review_stats():
    """获取统计数据用于图表"""
    try:
        review_type = request.args.get('type', 'mr')
        authors = request.args.getlist('authors') if request.args.get('authors') else None
        project_names = request.args.getlist('project_names') if request.args.get('project_names') else None
        updated_at_gte = request.args.get('updated_at_gte')
        updated_at_lte = request.args.get('updated_at_lte')
        
        if updated_at_gte:
            updated_at_gte = int(updated_at_gte)
        else:
            updated_at_gte = None
            
        if updated_at_lte:
            updated_at_lte = int(updated_at_lte)
        else:
            updated_at_lte = None
        
        if review_type == 'push':
            df = ReviewService().get_push_review_logs(
                authors=authors,
                project_names=project_names,
                updated_at_gte=updated_at_gte,
                updated_at_lte=updated_at_lte
            )
        else:
            df = ReviewService().get_mr_review_logs(
                authors=authors,
                project_names=project_names,
                updated_at_gte=updated_at_gte,
                updated_at_lte=updated_at_lte
            )
        
        if df.empty:
            return jsonify({
                'project_counts': [],
                'project_scores': [],
                'author_counts': [],
                'author_scores': [],
                'author_code_lines': []
            })
        
        # 项目提交次数
        project_counts = df['project_name'].value_counts().reset_index()
        project_counts.columns = ['name', 'count']
        
        # 项目平均分数
        project_scores = df.groupby('project_name')['score'].mean().reset_index()
        project_scores.columns = ['name', 'average_score']
        
        # 人员提交次数
        author_counts = df['author'].value_counts().reset_index()
        author_counts.columns = ['name', 'count']
        
        # 人员平均分数
        author_scores = df.groupby('author')['score'].mean().reset_index()
        author_scores.columns = ['name', 'average_score']
        
        # 人员代码行数
        author_code_lines = []
        if 'additions' in df.columns and 'deletions' in df.columns:
            df['total_lines'] = df['additions'] + df['deletions']
            author_code_lines_df = df.groupby('author')['total_lines'].sum().reset_index()
            author_code_lines_df.columns = ['name', 'code_lines']
            author_code_lines = author_code_lines_df.to_dict(orient='records')
        
        return jsonify({
            'project_counts': project_counts.to_dict(orient='records'),
            'project_scores': project_scores.to_dict(orient='records'),
            'author_counts': author_counts.to_dict(orient='records'),
            'author_scores': author_scores.to_dict(orient='records'),
            'author_code_lines': author_code_lines
        })
    except Exception as e:
        logger.error(f"Failed to get review stats: {e}")
        return jsonify({'error': str(e)}), 500


@ui_app.route('/api/review/filter-options', methods=['GET'])
def get_filter_options():
    """获取所有可用的筛选选项（用户名和项目名）"""
    try:
        review_type = request.args.get('type', 'mr')
        
        # 获取所有数据（不应用任何筛选条件）
        if review_type == 'push':
            df = ReviewService().get_push_review_logs()
        else:
            df = ReviewService().get_mr_review_logs()
        
        # 提取唯一的用户名和项目名
        authors = []
        project_names = []
        
        if not df.empty:
            authors = sorted(df['author'].dropna().unique().tolist())
            project_names = sorted(df['project_name'].dropna().unique().tolist())
        
        return jsonify({
            'authors': authors,
            'project_names': project_names
        })
    except Exception as e:
        logger.error(f"Failed to get filter options: {e}")
        return jsonify({'error': str(e)}), 500


@ui_app.route('/api/admin/oauth-settings', methods=['POST'])
def save_oauth_settings():
    payload = request.get_json(silent=True) or {}
    admin_password = os.getenv('ADMIN_SETUP_PASSWORD')
    if not admin_password or payload.get('admin_password') != admin_password:
        return jsonify({'error': 'forbidden'}), 403

    client_id = (payload.get('client_id') or '').strip()
    client_secret = (payload.get('client_secret') or '').strip()
    callback_url = (payload.get('callback_url') or '').strip()
    webhook_url = (payload.get('webhook_url') or '').strip()

    if not client_id or not client_secret:
        return jsonify({'error': 'missing_fields'}), 400

    SETTINGS.set('GITHUB_OAUTH_CLIENT_ID', client_id)
    SETTINGS.set('GITHUB_OAUTH_CLIENT_SECRET', client_secret)
    if callback_url:
        SETTINGS.set('GITHUB_OAUTH_CALLBACK_URL', callback_url)
    if webhook_url:
        SETTINGS.set('REVIEW_WEBHOOK_URL', webhook_url)

    return jsonify({'success': True}), 200


@ui_app.route('/oauth/github/start', methods=['GET'])
def github_oauth_start():
    repo_url = request.args.get('repo_url', '').strip()
    repo_full_name = parse_github_repo_url(repo_url)
    if not repo_full_name:
        message = quote("无法解析仓库地址，请使用 https://github.com/owner/repo")
        return redirect(f"/?oauth=error&message={message}")
    cleanup_oauth_state()
    authorize_url, error = build_github_oauth_redirect(repo_full_name)
    if error:
        message = quote("管理员未完成初始化，请联系管理员")
        return redirect(f"/?oauth=error&message={message}")
    return redirect(authorize_url)


@ui_app.route('/oauth/github/callback', methods=['GET'])
def github_oauth_callback():
    code = request.args.get('code')
    state = request.args.get('state')
    cleanup_oauth_state()
    if not code or not state or state not in oauth_state_store:
        message = quote("授权状态无效或已过期，请重新授权")
        return redirect(f"/?oauth=error&message={message}")
    state_payload = oauth_state_store.pop(state)
    repo_full_name = state_payload.get("repo_full_name")
    callback_url = os.getenv('GITHUB_OAUTH_CALLBACK_URL') or SETTINGS.get('GITHUB_OAUTH_CALLBACK_URL')
    if not callback_url:
        callback_url = request.url_root.rstrip('/') + '/oauth/github/callback'
    access_token, error = exchange_github_token(code, callback_url)
    if error:
        message = quote("授权失败，请联系管理员")
        if error != "not_configured":
            message = quote("授权失败，请稍后重试")
        return redirect(f"/?oauth=error&message={message}")
    GitHubOAuthTokenStore().save_token(repo_full_name, access_token)
    success, action_or_error = upsert_github_webhook(repo_full_name, access_token)
    if not success:
        message = quote("授权失败，请稍后重试")
        return redirect(f"/?oauth=error&message={message}")
    repo_param = quote(repo_full_name)
    action_param = quote(action_or_error)
    return redirect(f"/?oauth=success&repo={repo_param}&action={action_param}")


# 前端路由 - 必须在 API 路由之后定义，避免冲突
@ui_app.route('/')
def index():
    """提供前端页面"""
    return send_from_directory(WEB_DIR, 'index.html')

@ui_app.route('/<path:path>')
def serve_static(path):
    """提供静态文件"""
    # 排除 API 路由
    if path.startswith('api/'):
        return None
    # 确保路径安全
    if '..' in path or path.startswith('/'):
        return None
    return send_from_directory(WEB_DIR, path)

if __name__ == '__main__':
    port = int(os.environ.get('UI_PORT', 5002))
    ui_app.run(host='0.0.0.0', port=port, debug=False)
