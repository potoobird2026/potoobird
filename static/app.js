let isStreaming=false;
function sendMessage(){
    if(isStreaming)return;
    const input=document.getElementById('user-input');
    const message=input.value.trim();
    if(!message)return;
    appendMessage('user',message);
    input.value='';
    input.style.height='auto';
    showTyping();
    isStreaming=true;
    document.getElementById('send-btn').disabled=true;
    fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message})})
    .then(r=>r.json())
    .then(data=>{
        hideTyping();
        if(data.error)appendMessage('agent','❌ '+data.error);
        else appendMessage('agent',data.response);
        isStreaming=false;
        document.getElementById('send-btn').disabled=false;
        loadMemories();loadSkills();loadMCPServers();
    })
    .catch(e=>{
        hideTyping();
        appendMessage('agent','❌ 连接错误: '+e.message);
        isStreaming=false;
        document.getElementById('send-btn').disabled=false;
    });
}
function appendMessage(role,content){
    const messages=document.getElementById('chat-messages');
    const div=document.createElement('div');
    div.className='message '+role;
    div.innerHTML='<div class="avatar">'+(role==='user'?'👤':'🤖')+'</div><div class="content">'+escapeHtml(content)+'</div>';
    messages.appendChild(div);
    messages.scrollTop=messages.scrollHeight;
}
function showTyping(){
    const messages=document.getElementById('chat-messages');
    const div=document.createElement('div');
    div.id='typing';
    div.className='message agent';
    div.innerHTML='<div class="avatar">🤖</div><div class="content">思考中...</div>';
    messages.appendChild(div);
    messages.scrollTop=messages.scrollHeight;
}
function hideTyping(){const el=document.getElementById('typing');if(el)el.remove()}
function escapeHtml(text){const div=document.createElement('div');div.textContent=text;return div.innerHTML}
function loadMemories(){
    fetch('/api/memory').then(r=>r.json()).then(data=>{
        document.getElementById('memory-count').textContent=data.memories.length+' 条';
    }).catch(()=>{});
}
function loadSkills(){
    fetch('/api/skills').then(r=>r.json()).then(data=>{
        const panel=document.getElementById('skill-panel');
        if(data.skills&&data.skills.length){
            panel.innerHTML=data.skills.map(s=>{
                const status=s.enabled?'🟢':'⚪';
                const tools=s.tools?s.tools.length+'工具':'';
                const actions=[];
                if(s.enabled) actions.push('<button onclick="disableSkill(\''+s.id+'\')">禁用</button>');
                else actions.push('<button onclick="enableSkill(\''+s.id+'\')">启用</button>');
                actions.push('<button onclick="uninstallSkill(\''+s.id+'\')">卸载</button>');
                return '<div class="skill-item">'+status+' '+s.name+' ('+tools+')<br><span class="skill-actions">'+actions.join('')+'</span></div>';
            }).join('');
        }else{
            panel.innerHTML='<div class="skill-item">无已安装 Skill</div>';
        }
    }).catch(()=>{
        document.getElementById('skill-panel').innerHTML='<div class="skill-item">加载失败</div>';
    });
}
function toggleSkillForm(){
    const form=document.getElementById('skill-add-form');
    form.style.display=form.style.display==='none'?'block':'none';
}
function installSkill(){
    const path=document.getElementById('skill-path').value.trim();
    if(!path)return;
    fetch('/api/skills/install',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})})
    .then(r=>r.json()).then(data=>{
        if(data.error)alert('安装失败: '+data.error);
        loadSkills();
        document.getElementById('skill-path').value='';
        document.getElementById('skill-add-form').style.display='none';
    }).catch(e=>alert('安装错误: '+e.message));
}
function enableSkill(id){
    fetch('/api/skills/'+id+'/enable',{method:'POST'}).then(r=>r.json()).then(d=>loadSkills()).catch(()=>{});
}
function disableSkill(id){
    fetch('/api/skills/'+id+'/disable',{method:'POST'}).then(r=>r.json()).then(d=>loadSkills()).catch(()=>{});
}
function uninstallSkill(id){
    if(!confirm('确认卸载 Skill: '+id+'?'))return;
    fetch('/api/skills/'+id+'/uninstall',{method:'POST'}).then(r=>r.json()).then(d=>loadSkills()).catch(()=>{});
}
function loadMCPServers(){
    fetch('/api/mcp/servers').then(r=>r.json()).then(data=>{
        const panel=document.getElementById('mcp-panel');
        const servers=data.servers||[];
        if(servers.length){
            panel.innerHTML=servers.map(s=>{
                const status=s.connected?'🟢':'🔴';
                const tools=s.tool_count?s.tool_count+'工具':'';
                const actions=[];
                if(!s.connected&&s.enabled) actions.push('<button onclick="connectMCP(\''+s.id+'\')">连接</button>');
                if(s.connected) actions.push('<button onclick="disconnectMCP(\''+s.id+'\')">断开</button>');
                actions.push('<button onclick="removeMCP(\''+s.id+'\')">删除</button>');
                return '<div class="mcp-item">'+status+' '+s.name+' ('+s.transport+') '+tools+'<br><span class="mcp-actions">'+actions.join('')+'</span></div>';
            }).join('');
        }else{
            panel.innerHTML='<div class="mcp-item">无已配置服务器</div>';
        }
    }).catch(()=>{
        document.getElementById('mcp-panel').innerHTML='<div class="mcp-item">加载失败</div>';
    });
}
function toggleMCPForm(){
    const form=document.getElementById('mcp-add-form');
    form.style.display=form.style.display==='none'?'block':'none';
}
function addMCPServer(){
    const name=document.getElementById('mcp-name').value.trim();
    const url=document.getElementById('mcp-url').value.trim();
    const transport=document.getElementById('mcp-transport').value;
    if(!name||!url)return;
    fetch('/api/mcp/servers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,url,transport})})
    .then(r=>r.json()).then(data=>{
        if(data.error)alert('添加失败: '+data.error);
        loadMCPServers();
        document.getElementById('mcp-name').value='';
        document.getElementById('mcp-url').value='';
        document.getElementById('mcp-add-form').style.display='none';
    }).catch(e=>alert('添加错误: '+e.message));
}
function connectMCP(id){
    fetch('/api/mcp/servers/'+id+'/connect',{method:'POST'}).then(r=>r.json()).then(d=>loadMCPServers()).catch(()=>{});
}
function disconnectMCP(id){
    fetch('/api/mcp/servers/'+id+'/disconnect',{method:'POST'}).then(r=>r.json()).then(d=>loadMCPServers()).catch(()=>{});
}
function removeMCP(id){
    if(!confirm('确认删除 MCP 服务器: '+id+'?'))return;
    fetch('/api/mcp/servers/'+id,{method:'DELETE'}).then(r=>r.json()).then(d=>loadMCPServers()).catch(()=>{});
}
document.getElementById('user-input').addEventListener('keydown',e=>{
    if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();}
});
document.getElementById('user-input').addEventListener('input',function(){
    this.style.height='auto';
    this.style.height=Math.min(this.scrollHeight,120)+'px';
});
loadMemories();loadSkills();loadMCPServers();
