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
  // Reliable action menus for entity rows (employees, vehicles, etc.).
  function closeMoreMenus(except){
    document.querySelectorAll(".more-menu.is-open").forEach(menu=>{
      if(menu!==except){
        menu.classList.remove("is-open");
        const button=menu.querySelector("[data-more-toggle]");
        const panel=menu.querySelector(".more-pop");
        button?.setAttribute("aria-expanded","false");
        if(panel) panel.hidden=true;
      }
    });
  }
  document.addEventListener("click",event=>{
    const toggle=event.target.closest("[data-more-toggle]");
    if(toggle){
      event.preventDefault();
      event.stopPropagation();
      const menu=toggle.closest(".more-menu");
      const panel=menu?.querySelector(".more-pop");
      if(!menu || !panel)return;
      const willOpen=!menu.classList.contains("is-open");
      closeMoreMenus(willOpen?menu:null);
      menu.classList.toggle("is-open",willOpen);
      toggle.setAttribute("aria-expanded",willOpen?"true":"false");
      panel.hidden=!willOpen;
      return;
    }
    if(!event.target.closest(".more-menu")) closeMoreMenus(null);
  });
  document.addEventListener("keydown",event=>{
    if(event.key==="Escape") closeMoreMenus(null);
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

  // Searchable tree-based account selectors.
  function closeAccountPickers(except){
    document.querySelectorAll("[data-account-picker]").forEach(p=>{
      if(p!==except){
        const panel=p.querySelector("[data-account-panel]");
        if(panel) panel.hidden=true;
        p.classList.remove("open");
      }
    });
  }
  function filterAccountTree(picker,q){
    const needle=(q||"").trim().toLowerCase();
    const leaves=[...picker.querySelectorAll("[data-account-leaf]")];
    let count=0;
    leaves.forEach(leaf=>{
      const match=!needle || (leaf.dataset.accountLabelText||"").includes(needle);
      leaf.hidden=!match;
      if(match) count++;
    });
    const groups=[...picker.querySelectorAll("[data-account-group]")];
    groups.forEach(group=>{
      const match=!needle || (group.dataset.accountLabelText||"").includes(needle);
      group.hidden=!match && count>0;
    });
    const empty=picker.querySelector("[data-account-empty]");
    if(empty) empty.hidden=count!==0;
  }
  function initAccountPickers(){
    document.querySelectorAll("[data-account-picker]").forEach(picker=>{
      if(picker.dataset.accountReady==="1") return;
      picker.dataset.accountReady="1";
      const trigger=picker.querySelector("[data-account-trigger]");
      const panel=picker.querySelector("[data-account-panel]");
      const search=picker.querySelector("[data-account-search]");
      const value=picker.querySelector("[data-account-value]");
      const label=picker.querySelector("[data-account-label]");
      const leaves=[...picker.querySelectorAll("[data-account-leaf]")];
      trigger?.addEventListener("click",e=>{
        e.preventDefault();
        const willOpen=!!panel?.hidden;
        closeAccountPickers(willOpen?picker:null);
        if(panel) panel.hidden=!willOpen;
        picker.classList.toggle("open",willOpen);
        if(willOpen){search?.focus();filterAccountTree(picker,"");}
      });
      leaves.forEach(leaf=>leaf.addEventListener("click",()=>{
        value.value=leaf.dataset.accountId||"";
        label.textContent=leaf.querySelector("span:last-child")?.textContent?.trim()||"اختر الحساب";
        panel.hidden=true;
        picker.classList.remove("open");
        if(search) search.value="";
        filterAccountTree(picker,"");
        value.dispatchEvent(new Event("change",{bubbles:true}));
      }));
      search?.addEventListener("input",e=>filterAccountTree(picker,e.target.value));
      if(value?.value){
        const selected=leaves.find(x=>x.dataset.accountId===value.value);
        if(selected) label.textContent=selected.querySelector("span:last-child")?.textContent?.trim()||label.textContent;
      }
      filterAccountTree(picker,"");
    });
  }
  document.addEventListener("click",event=>{
    if(!event.target.closest("[data-account-picker]")) closeAccountPickers(null);
  });
  window.initAccountPickers=initAccountPickers;
  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",initAccountPickers);
  else initAccountPickers();

  // Confirm before logging out.
  document.addEventListener("submit",event=>{
    const form=event.target.closest('form[action*="/logout"]');
    if(form && !window.confirm("هل أنت متأكد من تسجيل الخروج؟")) event.preventDefault();
  });

  // Arabic amount-to-words helper for live previews.
  const arabicOnes=["","واحد","اثنان","ثلاثة","أربعة","خمسة","ستة","سبعة","ثمانية","تسعة"];
  const arabicTens=["","عشرة","عشرون","ثلاثون","أربعون","خمسون","ستون","سبعون","ثمانون","تسعون"];
  const arabicTeens=["عشرة","أحد عشر","اثنا عشر","ثلاثة عشر","أربعة عشر","خمسة عشر","ستة عشر","سبعة عشر","ثمانية عشر","تسعة عشر"];
  const arabicHundreds=["","مائة","مائتان","ثلاثمائة","أربعمائة","خمسمائة","ستمائة","سبعمائة","ثمانمائة","تسعمائة"];
  function under1000(n){
    if(n<10)return arabicOnes[n];
    if(n<20)return arabicTeens[n-10];
    if(n<100){const t=Math.floor(n/10),o=n%10;return o?arabicOnes[o]+" و"+arabicTens[t]:arabicTens[t];}
    const h=Math.floor(n/100),rest=n%100;
    return rest?arabicHundreds[h]+" و"+under1000(rest):arabicHundreds[h];
  }
  function arabicIntegerWords(n){
    n=Math.floor(Math.max(0,n));
    if(n===0)return "صفر";
    const scales=[
      [1000000000,"مليار","ملياران","مليارات"],
      [1000000,"مليون","مليونان","ملايين"],
      [1000,"ألف","ألفان","آلاف"]
    ];
    const parts=[];
    for(const [value,one,two,many] of scales){
      const q=Math.floor(n/value);
      if(!q)continue;
      n%=value;
      parts.push(q===1?one:q===2?two:under1000(q)+" "+many);
    }
    if(n)parts.push(under1000(n));
    return parts.join(" و");
  }
  function moneyToArabicWords(value,currency="ريال"){
    const n=Number(String(value||"").replace(/,/g,""));
    if(!Number.isFinite(n)||n<=0)return "";
    const whole=Math.floor(n);
    const fraction=Math.round((n-whole)*100);
    let out=arabicIntegerWords(whole)+" "+currency;
    if(fraction) out+=" و"+arabicIntegerWords(fraction)+" فلس";
    return out+" فقط";
  }
  function initMoneyWords(){
    document.querySelectorAll("[data-money-words]").forEach(input=>{
      if(input.dataset.moneyWordsReady==="1")return;
      input.dataset.moneyWordsReady="1";
      const target=document.getElementById(input.dataset.moneyWords);
      const currency=input.dataset.currency||"ريال";
      const update=()=>{if(target)target.textContent=moneyToArabicWords(input.value,currency)};
      input.addEventListener("input",update);
      update();
    });
  }
  window.moneyToArabicWords=moneyToArabicWords;
  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",initMoneyWords);
  else initMoneyWords();

})();