(function(){
  const byId=id=>document.getElementById(id);

  function openMenu(){
    byId("app-menu")?.classList.add("is-open");
    byId("app-menu-backdrop")?.classList.add("is-open");
    document.body.classList.add("menu-open");
  }
  function closeMenu(){
    byId("app-menu")?.classList.remove("is-open");
    byId("app-menu-backdrop")?.classList.remove("is-open");
    document.body.classList.remove("menu-open");
  }
  window.openAppMenu=openMenu;
  window.closeAppMenu=closeMenu;

  document.addEventListener("click",event=>{
    const open=event.target.closest("[data-menu-open]");
    const close=event.target.closest("[data-menu-close]");
    if(open){event.preventDefault();openMenu();return;}
    if(close){event.preventDefault();closeMenu();return;}
    if(event.target.closest(".sidebar-nav a")) closeMenu();

    const toggle=event.target.closest("[data-toggle-panel]");
    if(toggle){
      event.preventDefault();
      const panel=byId(toggle.dataset.togglePanel);
      if(panel) panel.classList.toggle("is-open");
    }
  });

  document.addEventListener("keydown",event=>{if(event.key==="Escape")closeMenu();});
  document.addEventListener("click",event=>{
    document.querySelectorAll(".more-menu[open]").forEach(el=>{
      if(!el.contains(event.target)) el.removeAttribute("open");
    });
  });

  let deferredPrompt=null;
  const fab=byId("pwa-install-fab");
  window.addEventListener("beforeinstallprompt",event=>{
    event.preventDefault();
    deferredPrompt=event;
    try{if(localStorage.getItem("kareem_pwa_dismissed")!=="1") fab?.removeAttribute("hidden");}catch(e){fab?.removeAttribute("hidden");}
  });
  document.addEventListener("click",async event=>{
    if(event.target.closest("[data-pwa-install]") && deferredPrompt){
      deferredPrompt.prompt();
      try{await deferredPrompt.userChoice;}catch(e){}
      deferredPrompt=null;
      fab?.setAttribute("hidden","");
    }
    if(event.target.closest("[data-pwa-dismiss]")){
      fab?.setAttribute("hidden","");
      try{localStorage.setItem("kareem_pwa_dismissed","1");}catch(e){}
    }
  });
  window.addEventListener("appinstalled",()=>{fab?.setAttribute("hidden","");deferredPrompt=null;});

  if("serviceWorker" in navigator){
    window.addEventListener("load",()=>navigator.serviceWorker.register("/static/sw.js").catch(()=>{}));
  }
})();