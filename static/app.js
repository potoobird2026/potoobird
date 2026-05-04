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
            panel.innerHTML=data.skills.map(s=>
                '<div class="skill-item">'+s.name+' ('+s.tools.length+'工具)</div>'
            ).join('');
        }else{
            panel.innerHTML='<div class="skill-item">无已加载 Skill</div>';
        }
    }).catch(()=>{
        document.getElementById('skill-panel').innerHTML='<div class="skill-item">加载失败</div>';
    });
}
function loadMCPServers(){
    fetch('/api/mcp/status').then(r=>r.json()).then(data=>{
        const panel=document.getElementById('mcp-panel');
        if(data.servers&&data.servers.length){
            panel.innerHTML=data.servers.map(s=>{
                const status=s.connected?'🟢':'🔴';
                const tools=s.tools&&s.tools.length?' ('+s.tools.length+'工具)':'';
                return '<div class="mcp-item">'+status+' '+s.name+tools+'</div>';
            }).join('');
        }else{
            panel.innerHTML='<div class="mcp-item">无已连接服务器</div>';
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
    if(!name||!url)return;
    fetch('/api/mcp/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,url})})
    .then(r=>r.json())
    .then(data=>{
        if(data.error)alert('连接失败: '+data.error);
        loadMCPServers();
        document.getElementById('mcp-name').value='';
        document.getElementById('mcp-url').value='';
        document.getElementById('mcp-add-form').style.display='none';
    }).catch(e=>alert('连接错误: '+e.message));
}
document.getElementById('user-input').addEventListener('keydown',e=>{
    if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();}
});
document.getElementById('user-input').addEventListener('input',function(){
    this.style.height='auto';
    this.style.height=Math.min(this.scrollHeight,120)+'px';
});
loadMemories();loadSkills();loadMCPServers();
