(function(){
  var docs = [
    { title: "Start Here", path: "FD_DOCUMENTATION.md" },
    { title: "Roles", path: "ROLES.md" },
    { title: "WI Template", path: "WI_TEMPLATE.md" },
    { title: "Milestone Template", path: "MILESTONE_TEMPLATE.md" },
    { title: "E2E Verification", path: "E2E_VERIFICATION.md" },
    { title: "Release Runbook", path: "RELEASE_RUNBOOK.md" }
  ];

  function byId(x){ return document.getElementById(x); }

  var nav = byId("navList");
  var raw = byId("raw");
  var render = byId("render");
  var titleEl = byId("docTitle");
  var copyBtn = byId("copyBtn");

  function setMode(showRaw){
    raw.style.display = showRaw ? "block" : "none";
    render.style.display = showRaw ? "none" : "block";
    render.setAttribute("aria-hidden", showRaw ? "true" : "false");
  }

  function loadDoc(item){
    titleEl.textContent = item.title + " (" + item.path + ")";
    fetch(item.path).then(function(r){
      if(!r.ok){ throw new Error("Fetch failed: " + item.path); }
      return r.text();
    }).then(function(t){
      raw.textContent = t;
      render.innerHTML = window.MDLite.render(t);
      setMode(false);
    }).catch(function(e){
      raw.textContent = String(e);
      render.innerHTML = "";
      setMode(true);
    });
  }

  function initNav(){
    docs.forEach(function(item, idx){
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = "#doc=" + encodeURIComponent(item.path);
      a.textContent = item.title;
      a.addEventListener("click", function(ev){
        ev.preventDefault();
        loadDoc(item);
        history.replaceState(null, "", a.href);
      });
      li.appendChild(a);
      nav.appendChild(li);
      if(idx===0){ loadDoc(item); }
    });
  }

  copyBtn.addEventListener("click", function(){
    var t = raw.textContent || "";
    if(!navigator.clipboard){ return; }
    navigator.clipboard.writeText(t);
  });

  initNav();
})();
