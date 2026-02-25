(function(){
  function esc(s){
    return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  }
  function inline(s){
    var out = esc(s);
    out = out.replace(/`([^`]+)`/g, function(_,a){ return "<code>"+esc(a)+"</code>"; });
    out = out.replace(/\*\*([^*]+)\*\*/g, function(_,a){ return "<strong>"+esc(a)+"</strong>"; });
    out = out.replace(/\*([^*]+)\*/g, function(_,a){ return "<em>"+esc(a)+"</em>"; });
    return out;
  }
  function render(md){
    var lines = md.replace(/\r\n/g,"\n").split("\n");
    var html = [];
    var inCode = false;
    var codeBuf = [];
    var inList = false;

    function closeList(){
      if(inList){ html.push("</ul>"); inList=false; }
    }
    function flushCode(){
      if(inCode){
        html.push("<pre><code>"+esc(codeBuf.join("\n"))+"</code></pre>");
        inCode=false;
        codeBuf=[];
      }
    }

    for(var i=0;i<lines.length;i++){
      var line = lines[i];

      if(line.trim().startsWith("```")){
        if(inCode){ flushCode(); }
        else { closeList(); inCode=true; }
        continue;
      }
      if(inCode){
        codeBuf.push(line);
        continue;
      }

      var m1 = line.match(/^#\s+(.*)$/);
      var m2 = line.match(/^##\s+(.*)$/);
      var m3 = line.match(/^###\s+(.*)$/);
      var ml = line.match(/^\-\s+(.*)$/);

      if(m1){ closeList(); html.push("<h1>"+inline(m1[1])+"</h1>"); continue; }
      if(m2){ closeList(); html.push("<h2>"+inline(m2[1])+"</h2>"); continue; }
      if(m3){ closeList(); html.push("<h3>"+inline(m3[1])+"</h3>"); continue; }

      if(ml){
        if(!inList){ html.push("<ul>"); inList=true; }
        html.push("<li>"+inline(ml[1])+"</li>");
        continue;
      }

      if(line.trim()===""){ closeList(); continue; }

      closeList();
      html.push("<p>"+inline(line)+"</p>");
    }
    closeList();
    flushCode();
    return html.join("\n");
  }
  window.MDLite = { render: render };
})();
