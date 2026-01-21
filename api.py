from dotenv import load_dotenv

load_dotenv("config/.env")

import atexit
import json
import os
import traceback
from datetime import datetime
from urllib.parse import urlparse
import pandas as pd

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, request, jsonify, send_from_directory
import os

from src.gitlab.webhook_handler import slugify_url
from src.service.github_oauth_service import GitHubOAuthTokenStore
from src.queue.worker import handle_merge_request_event, handle_push_event, handle_github_pull_request_event, \
    handle_github_push_event, handle_gitea_push_event, handle_gitea_pull_request_event
from src.service.review_service import ReviewService
from src.utils.messaging import notifier
from src.utils.log import logger
from src.utils.queue import handle_queue
from src.utils.reporter import Reporter

from src.utils.config_checker import check_config

api_app = Flask(__name__, static_folder='web', static_url_path='')

push_review_enabled = os.environ.get('PUSH_REVIEW_ENABLED', '0') == '1'


@api_app.route('/')
def home():
    return "<h2>The server is running.</h2>"


@api_app.route('/api/review/logs', methods=['GET'])
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


@api_app.route('/api/review/stats', methods=['GET'])
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


@api_app.route('/review/daily_report', methods=['GET'])
def daily_report():
    # 获取当前日期0点和23点59分59秒的时间戳
    start_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    end_time = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0).timestamp()

    try:
        if push_review_enabled:
            df = ReviewService().get_push_review_logs(updated_at_gte=start_time, updated_at_lte=end_time)
        else:
            df = ReviewService().get_mr_review_logs(updated_at_gte=start_time, updated_at_lte=end_time)

        if df.empty:
            logger.info("No data to process.")
            return jsonify({'message': 'No data to process.'}), 200
        # 去重：基于 (author, message) 组合
        df_unique = df.drop_duplicates(subset=["author", "commit_messages"])
        # 按照 author 排序
        df_sorted = df_unique.sort_values(by="author")
        # 转换为适合生成日报的格式
        commits = df_sorted.to_dict(orient="records")
        # 生成日报内容
        report_txt = Reporter().generate_report(json.dumps(commits))
        # 发送钉钉通知
        notifier.send_notification(content=report_txt, msg_type="markdown", title="代码提交日报")

        # 返回生成的日报内容
        return json.dumps(report_txt, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Failed to generate daily report: {e}")
        return jsonify({'message': f"Failed to generate daily report: {e}"}), 500


def setup_scheduler():
    """
    配置并启动定时任务调度器
    """
    try:
        scheduler = BackgroundScheduler()
        crontab_expression = os.getenv('REPORT_CRONTAB_EXPRESSION', '0 18 * * 1-5')
        cron_parts = crontab_expression.split()
        cron_minute, cron_hour, cron_day, cron_month, cron_day_of_week = cron_parts

        # Schedule the task based on the crontab expression
        scheduler.add_job(
            daily_report,
            trigger=CronTrigger(
                minute=cron_minute,
                hour=cron_hour,
                day=cron_day,
                month=cron_month,
                day_of_week=cron_day_of_week
            )
        )

        # Start the scheduler
        scheduler.start()
        logger.info("Scheduler started successfully.")

        # Shut down the scheduler when exiting the app
        atexit.register(lambda: scheduler.shutdown())
    except Exception as e:
        logger.error(f"Error setting up scheduler: {e}")
        logger.error(traceback.format_exc())


# 处理 GitLab Merge Request Webhook
@api_app.route('/review/webhook', methods=['POST'])
def handle_webhook():
    # 记录请求头信息，用于调试
    logger.debug(f'Request headers: {dict(request.headers)}')
    logger.debug(f'Content-Type: {request.content_type}')
    
    # 获取请求的JSON数据
    # 尝试多种方式获取 JSON 数据
    data = None
    if request.is_json:
        data = request.get_json()
    else:
        # 如果 Content-Type 不是 application/json，尝试直接解析
        try:
            if request.data:
                data = json.loads(request.data)
                logger.info('Parsed JSON from request.data')
        except Exception as e:
            logger.error(f'Failed to parse JSON: {str(e)}')
            return jsonify({"error": f"Invalid JSON format: {str(e)}"}), 400
    
    if not data:
        logger.error('No data found in request')
        return jsonify({"error": "Invalid JSON or empty data"}), 400

    # 判断 webhook 来源
    # 注意：Gitea 为了兼容性会同时发送 X-GitHub-Event 和 X-Gitea-Event
    # 所以需要优先检查 X-Gitea-Event（如果存在，一定是 Gitea）
    github_event = request.headers.get('X-GitHub-Event')
    gitea_event = request.headers.get('X-Gitea-Event')
    
    logger.debug(f'GitHub event: {github_event}, Gitea event: {gitea_event}')

    # 优先识别 Gitea（因为 Gitea 会同时发送两种 header，但 GitHub 不会发送 Gitea header）
    if gitea_event:  # Gitea webhook（优先）
        return handle_gitea_webhook(gitea_event, data)
    elif github_event:  # GitHub webhook
        return handle_github_webhook(github_event, data)
    else:  # GitLab webhook（默认）
        return handle_gitlab_webhook(data)


def handle_github_webhook(event_type, data):
    # 获取GitHub配置
    repo_full_name = data.get('repository', {}).get('full_name')
    github_token = os.getenv('GITHUB_ACCESS_TOKEN') or request.headers.get('X-GitHub-Token')
    if not github_token and repo_full_name:
        github_token = GitHubOAuthTokenStore().get_token(repo_full_name)
    if not github_token:
        return jsonify({'message': 'Missing GitHub access token'}), 400

    github_url = os.getenv('GITHUB_URL') or 'https://github.com'
    github_url_slug = slugify_url(github_url)

    # 打印整个payload数据
    logger.info(f'Received GitHub event: {event_type}')
    logger.info(f'Payload: {json.dumps(data)}')

    if event_type == "pull_request":
        # 使用handle_queue进行异步处理
        handle_queue(handle_github_pull_request_event, data, github_token, github_url, github_url_slug)
        # 立马返回响应
        return jsonify(
            {'message': f'GitHub request received(event_type={event_type}), will process asynchronously.'}), 200
    elif event_type == "push":
        # 使用handle_queue进行异步处理
        handle_queue(handle_github_push_event, data, github_token, github_url, github_url_slug)
        # 立马返回响应
        return jsonify(
            {'message': f'GitHub request received(event_type={event_type}), will process asynchronously.'}), 200
    else:
        error_message = f'Only pull_request and push events are supported for GitHub webhook, but received: {event_type}.'
        logger.error(error_message)
        return jsonify(error_message), 400


def handle_gitlab_webhook(data):
    object_kind = data.get("object_kind")

    # 优先从请求头获取，如果没有，则从环境变量获取，如果没有，则从推送事件中获取
    gitlab_url = os.getenv('GITLAB_URL') or request.headers.get('X-Gitlab-Instance')
    if not gitlab_url:
        repository = data.get('repository')
        if not repository:
            return jsonify({'message': 'Missing GitLab URL'}), 400
        homepage = repository.get("homepage")
        if not homepage:
            return jsonify({'message': 'Missing GitLab URL'}), 400
        try:
            parsed_url = urlparse(homepage)
            gitlab_url = f"{parsed_url.scheme}://{parsed_url.netloc}/"
        except Exception as e:
            return jsonify({"error": f"Failed to parse homepage URL: {str(e)}"}), 400

    # 优先从环境变量获取，如果没有，则从请求头获取
    gitlab_token = os.getenv('GITLAB_ACCESS_TOKEN') or request.headers.get('X-Gitlab-Token')
    # 如果gitlab_token为空，返回错误
    if not gitlab_token:
        return jsonify({'message': 'Missing GitLab access token'}), 400

    gitlab_url_slug = slugify_url(gitlab_url)

    # 打印整个payload数据，或根据需求进行处理
    logger.info(f'Received event: {object_kind}')
    logger.info(f'Payload: {json.dumps(data)}')

    # 处理Merge Request Hook
    if object_kind == "merge_request":
        # 创建一个新进程进行异步处理
        handle_queue(handle_merge_request_event, data, gitlab_token, gitlab_url, gitlab_url_slug)
        # 立马返回响应
        return jsonify(
            {'message': f'Request received(object_kind={object_kind}), will process asynchronously.'}), 200
    elif object_kind == "push":
        # 创建一个新进程进行异步处理
        # TODO check if PUSH_REVIEW_ENABLED is needed here
        handle_queue(handle_push_event, data, gitlab_token, gitlab_url, gitlab_url_slug)
        # 立马返回响应
        return jsonify(
            {'message': f'Request received(object_kind={object_kind}), will process asynchronously.'}), 200
    else:
        error_message = f'Only merge_request and push events are supported (both Webhook and System Hook), but received: {object_kind}.'
        logger.error(error_message)
        return jsonify(error_message), 400


def handle_gitea_webhook(event_type, data):
    logger.info(f'Processing Gitea webhook, event_type: {event_type}')
    
    # 获取 Gitea 配置
    gitea_token = os.getenv('GITEA_ACCESS_TOKEN') or request.headers.get('X-Gitea-Token')
    if not gitea_token:
        error_msg = 'Missing Gitea access token. Please set GITEA_ACCESS_TOKEN environment variable or provide X-Gitea-Token header.'
        logger.error(error_msg)
        return jsonify({'message': error_msg}), 400

    # 获取 Gitea URL
    gitea_url = os.getenv('GITEA_URL') or request.headers.get('X-Gitea-Instance')
    if not gitea_url:
        # 从 payload 中提取
        repository = data.get('repository', {})
        logger.debug(f'Repository data: {repository}')
        if repository:
            html_url = repository.get('html_url', '')
            logger.debug(f'HTML URL from repository: {html_url}')
            if html_url:
                try:
                    parsed_url = urlparse(html_url)
                    gitea_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                    logger.info(f'Extracted Gitea URL from payload: {gitea_url}')
                except Exception as e:
                    error_msg = f"Failed to parse repository URL: {str(e)}"
                    logger.error(error_msg)
                    return jsonify({"error": error_msg}), 400
        if not gitea_url:
            error_msg = 'Missing Gitea URL. Please set GITEA_URL environment variable, provide X-Gitea-Instance header, or ensure repository.html_url is present in payload.'
            logger.error(error_msg)
            logger.debug(f'Payload keys: {list(data.keys())}')
            return jsonify({'message': error_msg}), 400

    # URL Slug 用于队列隔离和日志标识
    gitea_url_slug = slugify_url(gitea_url)

    logger.info(f'Received Gitea event: {event_type}')
    logger.info(f'Gitea URL: {gitea_url}')
    logger.debug(f'Payload: {json.dumps(data, ensure_ascii=False)}')

    # Push 事件优先级更高，先处理 Push
    if event_type == "push":
        handle_queue(handle_gitea_push_event, data, gitea_token, gitea_url, gitea_url_slug)
        return jsonify(
            {'message': f'Gitea request received(event_type={event_type}), will process asynchronously.'}), 200
    elif event_type == "pull_request":
        # 只处理 opened 和 synchronize action
        action = data.get('action', '')
        logger.debug(f'Pull Request action: {action}')
        if action not in ['opened', 'synchronize']:
            logger.info(f"Gitea Pull Request event, action={action}, ignored.")
            return jsonify(
                {'message': f'Gitea Pull Request event with action={action} is ignored, only opened and synchronize are supported.'}), 200
        handle_queue(handle_gitea_pull_request_event, data, gitea_token, gitea_url, gitea_url_slug)
        return jsonify(
            {'message': f'Gitea request received(event_type={event_type}), will process asynchronously.'}), 200
    elif event_type == "issue_comment":
        # issue_comment 事件：当 Issue 或 PR 上添加评论时触发
        # 由于我们的系统会自动在 Issue 上添加评论，Gitea 会发送这个 webhook
        # 我们不需要处理这个事件，静默忽略即可
        logger.debug(f'Gitea issue_comment event received, ignored (auto-generated by our system).')
        return jsonify(
            {'message': f'Gitea issue_comment event received and ignored (auto-generated by review system).'}), 200
    else:
        error_message = f'Only pull_request, push, and issue_comment events are supported for Gitea webhook, but received: {event_type}.'
        logger.error(error_message)
        return jsonify(error_message), 400


if __name__ == '__main__':
    check_config()
    # 启动定时任务调度器
    setup_scheduler()

    # 启动Flask API服务
    port = int(os.environ.get('SERVER_PORT', 5001))
    api_app.run(host='0.0.0.0', port=port)
