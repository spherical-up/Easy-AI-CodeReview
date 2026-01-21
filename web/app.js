// 全局变量
let currentData = [];
let charts = {};
let currentReviewType = 'mr';

// 初始化
document.addEventListener('DOMContentLoaded', function() {
    initOauthForm();

    // 设置默认日期
    const today = new Date();
    const sevenDaysAgo = new Date(today);
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
    
    document.getElementById('startDate').value = formatDate(sevenDaysAgo);
    document.getElementById('endDate').value = formatDate(today);
    
    // 监听审查类型变化
    document.querySelectorAll('input[name="reviewType"]').forEach(radio => {
        radio.addEventListener('change', function() {
            currentReviewType = this.value;
            // 更新表头显示
            if (currentReviewType === 'push') {
                document.getElementById('branchHeader').textContent = '分支';
                document.getElementById('targetBranchHeader').style.display = 'none';
                document.getElementById('urlHeader').style.display = 'none';
            } else {
                document.getElementById('branchHeader').textContent = '源分支';
                document.getElementById('targetBranchHeader').style.display = '';
                document.getElementById('urlHeader').style.display = '';
            }
            // 重新加载筛选器选项和数据
            loadFilterOptions().then(() => loadData());
        });
    });
    
    // 初始加载筛选器选项和数据
    loadFilterOptions().then(() => loadData());
    
    // 定时更新（每30秒）
    setInterval(updateLastUpdateTime, 30000);
    updateLastUpdateTime();
});

function initOauthForm() {
    const form = document.getElementById('githubOauthForm');
    const repoInput = document.getElementById('repoUrlInput');
    const statusEl = document.getElementById('oauthStatus');
    const adminToggle = document.getElementById('toggleAdminConfig');
    const adminForm = document.getElementById('adminOauthForm');
    const adminStatus = document.getElementById('adminOauthStatus');
    if (form && repoInput) {
        form.addEventListener('submit', function(event) {
            repoInput.value = repoInput.value.trim();
            if (!repoInput.value) {
                event.preventDefault();
                if (statusEl) {
                    statusEl.textContent = '请输入仓库地址，例如 https://github.com/owner/repo';
                    statusEl.className = 'text-sm mt-3 text-red-600';
                    statusEl.classList.remove('hidden');
                }
            }
        });
    }
    if (adminToggle && adminForm) {
        adminToggle.addEventListener('click', function() {
            adminForm.classList.toggle('hidden');
        });
    }
    if (adminForm) {
        adminForm.addEventListener('submit', async function(event) {
            event.preventDefault();
            const payload = {
                client_id: (document.getElementById('adminClientId').value || '').trim(),
                client_secret: (document.getElementById('adminClientSecret').value || '').trim(),
                callback_url: (document.getElementById('adminCallbackUrl').value || '').trim(),
                webhook_url: (document.getElementById('adminWebhookUrl').value || '').trim(),
                admin_password: (document.getElementById('adminPassword').value || '').trim()
            };
            if (!payload.client_id || !payload.client_secret || !payload.admin_password) {
                if (adminStatus) {
                    adminStatus.textContent = '请填写 Client ID、Client Secret 和管理员口令';
                    adminStatus.className = 'text-sm text-red-600';
                    adminStatus.classList.remove('hidden');
                }
                return;
            }
            try {
                const response = await fetch('/api/admin/oauth-settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!response.ok) {
                    throw new Error('保存失败');
                }
                if (adminStatus) {
                    adminStatus.textContent = '配置已保存';
                    adminStatus.className = 'text-sm text-green-600';
                    adminStatus.classList.remove('hidden');
                }
                document.getElementById('adminClientSecret').value = '';
                document.getElementById('adminPassword').value = '';
            } catch (error) {
                if (adminStatus) {
                    adminStatus.textContent = '保存失败，请检查管理员口令';
                    adminStatus.className = 'text-sm text-red-600';
                    adminStatus.classList.remove('hidden');
                }
            }
        });
    }
    const params = new URLSearchParams(window.location.search);
    const oauthStatus = params.get('oauth');
    if (statusEl && oauthStatus) {
        if (oauthStatus === 'success') {
            const repo = params.get('repo') || '';
            const action = params.get('action') || 'ok';
            statusEl.textContent = `授权成功，已${action} webhook：${repo}`;
            statusEl.className = 'text-sm mt-3 text-green-600';
        } else {
            const message = params.get('message') || '授权失败';
            statusEl.textContent = `授权失败：${message}`;
            statusEl.className = 'text-sm mt-3 text-red-600';
        }
        statusEl.classList.remove('hidden');
    }
}

// 格式化日期
function formatDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

// 更新最后更新时间
function updateLastUpdateTime() {
    const now = new Date();
    const timeStr = now.toLocaleString('zh-CN');
    document.getElementById('lastUpdate').textContent = `最后更新: ${timeStr}`;
}

// 切换标签页
function switchTab(tab) {
    // 更新按钮状态
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('active', 'border-blue-600', 'text-blue-600');
        btn.classList.add('text-gray-500');
    });
    
    // 隐藏所有内容
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.add('hidden');
    });
    
    // 显示选中的标签页
    if (tab === 'data') {
        document.getElementById('tabData').classList.add('active', 'border-blue-600', 'text-blue-600');
        document.getElementById('tabData').classList.remove('text-gray-500');
        document.getElementById('tabContentData').classList.remove('hidden');
    } else {
        document.getElementById('tabCharts').classList.add('active', 'border-blue-600', 'text-blue-600');
        document.getElementById('tabCharts').classList.remove('text-gray-500');
        document.getElementById('tabContentCharts').classList.remove('hidden');
        loadCharts();
    }
}

// 加载数据
async function loadData() {
    try {
        // 获取筛选条件
        const startDate = document.getElementById('startDate').value;
        const endDate = document.getElementById('endDate').value;
        const authors = Array.from(document.getElementById('authors').selectedOptions).map(opt => opt.value);
        const projectNames = Array.from(document.getElementById('projectNames').selectedOptions).map(opt => opt.value);
        
        // 构建查询参数
        const params = new URLSearchParams();
        params.append('type', currentReviewType);
        if (startDate) {
            const startTimestamp = Math.floor(new Date(startDate + ' 00:00:00').getTime() / 1000);
            params.append('updated_at_gte', startTimestamp);
        }
        if (endDate) {
            const endTimestamp = Math.floor(new Date(endDate + ' 23:59:59').getTime() / 1000);
            params.append('updated_at_lte', endTimestamp);
        }
        authors.forEach(author => params.append('authors', author));
        projectNames.forEach(project => params.append('project_names', project));
        
        // 显示加载状态
        const tbody = document.getElementById('dataTableBody');
        const colCount = currentReviewType === 'push' ? 7 : 9;
        tbody.innerHTML = `<tr><td colspan="${colCount}" class="px-6 py-4 text-center text-gray-500">加载中...</td></tr>`;
        
        // 获取数据
        const response = await fetch(`/api/review/logs?${params.toString()}`);
        const result = await response.json();
        
        if (result.error) {
            throw new Error(result.error);
        }
        
        currentData = result.data || [];
        
        // 更新统计信息
        document.getElementById('totalRecords').textContent = result.total || 0;
        document.getElementById('averageScore').textContent = (result.average_score || 0).toFixed(2);
        
        // 更新表格
        renderTable(currentData);
        
        // 更新筛选器选项
        updateFilterOptions(currentData);
        
        updateLastUpdateTime();
    } catch (error) {
        console.error('加载数据失败:', error);
        const tbody = document.getElementById('dataTableBody');
        const colCount = currentReviewType === 'push' ? 7 : 9;
        tbody.innerHTML = `<tr><td colspan="${colCount}" class="px-6 py-4 text-center text-red-500">加载失败: ${error.message}</td></tr>`;
    }
}

// 渲染表格
function renderTable(data) {
    const tbody = document.getElementById('dataTableBody');
    
        if (data.length === 0) {
        const colCount = currentReviewType === 'push' ? 7 : 9;
        tbody.innerHTML = `<tr><td colspan="${colCount}" class="px-6 py-4 text-center text-gray-500">暂无数据</td></tr>`;
        return;
    }
    
    // 根据审查类型更新表头
    if (currentReviewType === 'push') {
        document.getElementById('branchHeader').textContent = '分支';
        document.getElementById('targetBranchHeader').style.display = 'none';
        document.getElementById('urlHeader').style.display = 'none';
    } else {
        document.getElementById('branchHeader').textContent = '源分支';
        document.getElementById('targetBranchHeader').style.display = '';
        document.getElementById('urlHeader').style.display = '';
    }
    
    tbody.innerHTML = data.map(item => {
        const score = item.score || 0;
        const scoreColor = score >= 80 ? 'text-green-600' : score >= 60 ? 'text-yellow-600' : 'text-red-600';
        
        let row = `
            <tr class="hover:bg-gray-50">
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${escapeHtml(item.project_name || '')}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${escapeHtml(item.author || '')}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${escapeHtml(item.source_branch || item.branch || '')}</td>
        `;
        
        if (currentReviewType === 'mr') {
            row += `<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${escapeHtml(item.target_branch || '')}</td>`;
        }
        
        row += `
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${escapeHtml(item.updated_at || '')}</td>
                <td class="px-6 py-4 text-sm text-gray-900 max-w-xs truncate" title="${escapeHtml(item.commit_messages || '')}">${escapeHtml(item.commit_messages || '')}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${escapeHtml(item.delta || '')}</td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <span class="px-2 py-1 text-xs font-semibold rounded-full ${scoreColor}">${score.toFixed(1)}</span>
                </td>
        `;
        
        if (currentReviewType === 'mr' && item.url) {
            row += `<td class="px-6 py-4 whitespace-nowrap text-sm"><a href="${escapeHtml(item.url)}" target="_blank" class="text-blue-600 hover:text-blue-800">查看</a></td>`;
        }
        
        row += '</tr>';
        return row;
    }).join('');
}

// 加载所有筛选器选项
async function loadFilterOptions() {
    try {
        const response = await fetch(`/api/review/filter-options?type=${currentReviewType}`);
        const result = await response.json();
        
        if (result.error) {
            console.error('加载筛选器选项失败:', result.error);
            return;
        }
        
        // 获取当前已选中的选项
        const authorsSelect = document.getElementById('authors');
        const projectsSelect = document.getElementById('projectNames');
        const selectedAuthor = authorsSelect.value;
        const selectedProject = projectsSelect.value;
        
        // 更新作者选择器
        authorsSelect.innerHTML = '<option value="">全部</option>' + 
            (result.authors || []).map(author => 
                `<option value="${escapeHtml(author)}" ${selectedAuthor === author ? 'selected' : ''}>${escapeHtml(author)}</option>`
            ).join('');
        
        // 更新项目选择器
        projectsSelect.innerHTML = '<option value="">全部</option>' + 
            (result.project_names || []).map(project => 
                `<option value="${escapeHtml(project)}" ${selectedProject === project ? 'selected' : ''}>${escapeHtml(project)}</option>`
            ).join('');
    } catch (error) {
        console.error('加载筛选器选项失败:', error);
    }
}

// 更新筛选器选项（保留已存在的选项，添加新的选项）
function updateFilterOptions(data) {
    // 从当前数据中获取新的作者和项目名
    const newAuthors = [...new Set(data.map(item => item.author).filter(Boolean))];
    const newProjects = [...new Set(data.map(item => item.project_name).filter(Boolean))];
    
    // 获取当前选择器中的所有选项
    const authorsSelect = document.getElementById('authors');
    const projectsSelect = document.getElementById('projectNames');
    const existingAuthors = Array.from(authorsSelect.options).map(opt => opt.value).filter(v => v !== '');
    const existingProjects = Array.from(projectsSelect.options).map(opt => opt.value).filter(v => v !== '');
    const selectedAuthor = authorsSelect.value;
    const selectedProject = projectsSelect.value;
    
    // 合并现有选项和新选项
    const allAuthors = [...new Set([...existingAuthors, ...newAuthors])].sort();
    const allProjects = [...new Set([...existingProjects, ...newProjects])].sort();
    
    // 更新作者选择器
    authorsSelect.innerHTML = '<option value="">全部</option>' + 
        allAuthors.map(author => 
            `<option value="${escapeHtml(author)}" ${selectedAuthor === author ? 'selected' : ''}>${escapeHtml(author)}</option>`
        ).join('');
    
    // 更新项目选择器
    projectsSelect.innerHTML = '<option value="">全部</option>' + 
        allProjects.map(project => 
            `<option value="${escapeHtml(project)}" ${selectedProject === project ? 'selected' : ''}>${escapeHtml(project)}</option>`
        ).join('');
}

// 加载图表
async function loadCharts() {
    try {
        // 获取筛选条件
        const startDate = document.getElementById('startDate').value;
        const endDate = document.getElementById('endDate').value;
        const author = document.getElementById('authors').value;
        const projectName = document.getElementById('projectNames').value;
        
        // 构建查询参数
        const params = new URLSearchParams();
        params.append('type', currentReviewType);
        if (startDate) {
            const startTimestamp = Math.floor(new Date(startDate + ' 00:00:00').getTime() / 1000);
            params.append('updated_at_gte', startTimestamp);
        }
        if (endDate) {
            const endTimestamp = Math.floor(new Date(endDate + ' 23:59:59').getTime() / 1000);
            params.append('updated_at_lte', endTimestamp);
        }
        if (author) {
            params.append('authors', author);
        }
        if (projectName) {
            params.append('project_names', projectName);
        }
        
        // 获取统计数据
        const response = await fetch(`/api/review/stats?${params.toString()}`);
        const result = await response.json();
        
        if (result.error) {
            throw new Error(result.error);
        }
        
        // 渲染图表
        renderProjectCountChart(result.project_counts || []);
        renderProjectScoreChart(result.project_scores || []);
        renderAuthorCountChart(result.author_counts || []);
        renderAuthorScoreChart(result.author_scores || []);
        renderAuthorCodeLineChart(result.author_code_lines || []);
        
    } catch (error) {
        console.error('加载图表失败:', error);
    }
}

// 渲染项目提交次数图表
function renderProjectCountChart(data) {
    const ctx = document.getElementById('projectCountChart');
    if (charts.projectCount) {
        charts.projectCount.destroy();
    }
    
    charts.projectCount = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.map(item => item.name),
            datasets: [{
                label: '提交次数',
                data: data.map(item => item.count),
                backgroundColor: 'rgba(59, 130, 246, 0.6)',
                borderColor: 'rgba(59, 130, 246, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
}

// 渲染项目平均分数图表
function renderProjectScoreChart(data) {
    const ctx = document.getElementById('projectScoreChart');
    if (charts.projectScore) {
        charts.projectScore.destroy();
    }
    
    charts.projectScore = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.map(item => item.name),
            datasets: [{
                label: '平均分数',
                data: data.map(item => item.average_score),
                backgroundColor: 'rgba(147, 51, 234, 0.6)',
                borderColor: 'rgba(147, 51, 234, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100
                }
            }
        }
    });
}

// 渲染人员提交次数图表
function renderAuthorCountChart(data) {
    const ctx = document.getElementById('authorCountChart');
    if (charts.authorCount) {
        charts.authorCount.destroy();
    }
    
    charts.authorCount = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.map(item => item.name),
            datasets: [{
                label: '提交次数',
                data: data.map(item => item.count),
                backgroundColor: 'rgba(16, 185, 129, 0.6)',
                borderColor: 'rgba(16, 185, 129, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
}

// 渲染人员平均分数图表
function renderAuthorScoreChart(data) {
    const ctx = document.getElementById('authorScoreChart');
    if (charts.authorScore) {
        charts.authorScore.destroy();
    }
    
    charts.authorScore = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.map(item => item.name),
            datasets: [{
                label: '平均分数',
                data: data.map(item => item.average_score),
                backgroundColor: 'rgba(245, 158, 11, 0.6)',
                borderColor: 'rgba(245, 158, 11, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100
                }
            }
        }
    });
}

// 渲染人员代码行数图表
function renderAuthorCodeLineChart(data) {
    const ctx = document.getElementById('authorCodeLineChart');
    if (charts.authorCodeLine) {
        charts.authorCodeLine.destroy();
    }
    
    if (data.length === 0) {
        return;
    }
    
    charts.authorCodeLine = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.map(item => item.name),
            datasets: [{
                label: '代码行数',
                data: data.map(item => item.code_lines),
                backgroundColor: 'rgba(239, 68, 68, 0.6)',
                borderColor: 'rgba(239, 68, 68, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
}

// 重置筛选器
function resetFilters() {
    const today = new Date();
    const sevenDaysAgo = new Date(today);
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
    
    document.getElementById('startDate').value = formatDate(sevenDaysAgo);
    document.getElementById('endDate').value = formatDate(today);
    document.getElementById('authors').value = '';
    document.getElementById('projectNames').value = '';
    document.getElementById('typeMr').checked = true;
    currentReviewType = 'mr';
    
    loadFilterOptions().then(() => loadData());
}

// HTML 转义
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
