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
    if(event.target.closest(".sidebar-nav a") && window.matchMedia("(max-width:1100px)").matches) closeMenu();

    const toggle=event.target.closest("[data-toggle-panel]");
    if(toggle){
      event.preventDefault();
      const panel=byId(toggle.dataset.togglePanel);
      if(panel) panel.classList.toggle("is-open");
    }
  });


  // Sidebar tree behaves like a compact accordion. The desktop sidebar stays
  // fixed; on phones it remains a drawer and closes after choosing a page.
  function initSidebarTree(){
    const trees=[...document.querySelectorAll(".nav-tree")];
    if(!trees.length)return;
    trees.forEach(tree=>{
      const key="kareem_nav_"+[...trees].indexOf(tree);
      try{
        const saved=localStorage.getItem(key);
        if(saved==="open" && !tree.hasAttribute("open")) tree.setAttribute("open","");
        if(saved==="closed" && tree.hasAttribute("open") && !tree.querySelector(".active")) tree.removeAttribute("open");
      }catch(e){}
      tree.addEventListener("toggle",()=>{
        if(tree.open){
          trees.forEach(other=>{
            if(other!==tree) other.removeAttribute("open");
          });
          try{localStorage.setItem(key,"open");}catch(e){}
        }else{
          try{localStorage.setItem(key,"closed");}catch(e){}
        }
      });
    });
  }

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
    window.addEventListener("load",()=>{
      navigator.serviceWorker.register("/static/sw.js?v=20260922-2",{updateViaCache:"none"}).catch(()=>{});
    });
  }

  initSidebarTree();

  // Reusable collapsible account-tree picker.
  function closeAccountPickers(except){
    document.querySelectorAll("[data-account-picker]").forEach(p=>{
      if(p!==except){
        const panel=p.querySelector("[data-account-panel]");
        const trigger=p.querySelector("[data-account-trigger]");
        if(panel) panel.hidden=true;
        if(trigger) trigger.setAttribute("aria-expanded","false");
        p.classList.remove("open");
      }
    });
  }

  function accountPickerNodes(picker){
    return [...picker.querySelectorAll("[data-account-group],[data-account-leaf]")];
  }

  function accountPickerMap(picker){
    const map=new Map();
    accountPickerNodes(picker).forEach(node=>map.set(String(node.dataset.accountId),node));
    return map;
  }

  function accountNodeAncestors(node,map){
    const result=[];
    let parentId=String(node?.dataset.accountParentId||"");
    const guard=new Set();
    while(parentId && !guard.has(parentId)){
      guard.add(parentId);
      const parent=map.get(parentId);
      if(!parent) break;
      result.push(parent);
      parentId=String(parent.dataset.accountParentId||"");
    }
    return result;
  }

  function setAccountGroupExpanded(group,expanded){
    group.dataset.accountExpanded=expanded?"1":"0";
    group.setAttribute("aria-expanded",expanded?"true":"false");
    const icon=group.querySelector(".account-picker-caret i");
    if(icon) icon.className=expanded?"bi bi-chevron-down":"bi bi-chevron-left";
  }

  function accountPickerApply(picker){
    const search=picker.querySelector("[data-account-search]");
    const needle=(search?.value||"").trim().toLowerCase();
    const nodes=accountPickerNodes(picker);
    const leaves=nodes.filter(n=>n.hasAttribute("data-account-leaf"));
    const map=accountPickerMap(picker);
    const matchedLeaves=leaves.filter(leaf=>(leaf.dataset.accountLabelText||"").includes(needle));
    const matchingLeafIds=new Set(matchedLeaves.map(x=>String(x.dataset.accountId)));

    const groupHasMatch=group=>{
      if(!needle) return true;
      return leaves.some(leaf=>{
        if(!matchingLeafIds.has(String(leaf.dataset.accountId))) return false;
        return accountNodeAncestors(leaf,map).some(parent=>String(parent.dataset.accountId)===String(group.dataset.accountId))
          || (group.dataset.accountLabelText||"").includes(needle);
      });
    };

    nodes.forEach(node=>{
      const isGroup=node.hasAttribute("data-account-group");
      let show=true;
      if(needle){
        show=isGroup?groupHasMatch(node):matchedLeaves.includes(node);
      }
      if(!needle && isGroup){
        const hasSelectableDescendant=leaves.some(leaf=>accountNodeAncestors(leaf,map).some(parent=>String(parent.dataset.accountId)===String(node.dataset.accountId)));
        show=hasSelectableDescendant;
      }
      if(!needle && !isGroup){
        show=true;
      }

      if(show && !needle){
        const ancestors=accountNodeAncestors(node,map);
        if(ancestors.some(parent=>parent.hasAttribute("data-account-group") && parent.dataset.accountExpanded!=="1")){
          show=false;
        }
      }
      node.hidden=!show;

      if(!isGroup && !needle && node.dataset.accountSelected==="1"){
        node.classList.add("selected");
      }
    });

    const empty=picker.querySelector("[data-account-empty]");
    if(empty) empty.hidden=matchedLeaves.length!==0;
  }

  function openSelectedAccountPath(picker,selectedId){
    if(!selectedId) return;
    const map=accountPickerMap(picker);
    const selected=map.get(String(selectedId));
    if(!selected) return;
    accountNodeAncestors(selected,map).forEach(group=>setAccountGroupExpanded(group,true));
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
      const groups=[...picker.querySelectorAll("[data-account-group]")];
      const leaves=[...picker.querySelectorAll("[data-account-leaf]")];

      groups.forEach(group=>{
        setAccountGroupExpanded(group,false);
        group.addEventListener("click",e=>{
          e.preventDefault();
          const willExpand=group.dataset.accountExpanded!=="1";
          setAccountGroupExpanded(group,willExpand);
          accountPickerApply(picker);
        });
      });

      trigger?.addEventListener("click",e=>{
        e.preventDefault();
        const willOpen=!!panel?.hidden;
        closeAccountPickers(willOpen?picker:null);
        if(panel) panel.hidden=!willOpen;
        picker.classList.toggle("open",willOpen);
        trigger.setAttribute("aria-expanded",willOpen?"true":"false");
        if(willOpen){
          search?.focus();
          if(search) search.value="";
          accountPickerApply(picker);
        }
      });

      leaves.forEach(leaf=>leaf.addEventListener("click",()=>{
        value.value=leaf.dataset.accountId||"";
        label.textContent=(leaf.dataset.accountLabelText||"").replace(/\s+/g," / ").replace(/\s\/\s/g," / ");
        leaves.forEach(x=>x.classList.remove("selected"));
        leaf.classList.add("selected");
        leaf.dataset.accountSelected="1";
        panel.hidden=true;
        picker.classList.remove("open");
        trigger?.setAttribute("aria-expanded","false");
        if(search) search.value="";
        accountPickerApply(picker);
        value.dispatchEvent(new Event("change",{bubbles:true}));
      }));

      search?.addEventListener("input",()=>accountPickerApply(picker));

      if(value?.value){
        const selected=leaves.find(x=>x.dataset.accountId===value.value);
        if(selected){
          selected.classList.add("selected");
          selected.dataset.accountSelected="1";
          const parts=(selected.dataset.accountLabelText||"").split(/\s+/);
          label.textContent=selected.dataset.accountLabelText||label.textContent;
          openSelectedAccountPath(picker,value.value);
        }
      }
      accountPickerApply(picker);
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