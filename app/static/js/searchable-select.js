(function(){
"use strict";
const selector="select[data-searchable-select]:not([multiple])";
const instances=new WeakMap(),forms=new WeakSet();
let opened=null,uid=0;
const norm=v=>String(v??"").normalize("NFD").replace(/[\u064B-\u065F\u0670]/g,"").toLocaleLowerCase().trim();
const optText=o=>String(o?.textContent??"").replace(/\s+/g," ").trim();
const selected=s=>s.options[s.selectedIndex]||null;
function labelFor(s){
 const label=s.id&&[...document.querySelectorAll("label[for]")].find(x=>x.htmlFor===s.id);
 return label?.textContent.replace(/\s+/g," ").trim()||s.closest("label")?.textContent.replace(/\s+/g," ").trim()||s.getAttribute("aria-label")||"اختر عنصرًا";
}
function icon(cls){const e=document.createElement("i");e.className=cls;e.setAttribute("aria-hidden","true");return e;}
function close(inst,focus){
 if(!inst)return;inst.popup.hidden=true;inst.trigger.setAttribute("aria-expanded","false");
 window.removeEventListener("resize",inst.position);window.removeEventListener("scroll",inst.position,true);
 if(opened===inst)opened=null;if(focus)inst.trigger.focus({preventScroll:true});
}
function setup(s){
 if(!(s instanceof HTMLSelectElement)||s.multiple||s.dataset.ssReady==="1")return;
 s.dataset.ssReady="1";s.dataset.ssRequired=s.required?"1":"0";s.required=false;
 const wrap=document.createElement("div");wrap.className="ss-select-wrap";s.parentNode.insertBefore(wrap,s);wrap.appendChild(s);
 s.classList.add("ss-native-select");s.tabIndex=-1;s.setAttribute("aria-hidden","true");
 const trigger=document.createElement("button");trigger.type="button";trigger.className="ss-select-trigger form-select";
 trigger.id=s.id?s.id+"-select-trigger":"ss-select-trigger-"+(++uid);trigger.setAttribute("aria-haspopup","listbox");trigger.setAttribute("aria-expanded","false");trigger.setAttribute("aria-label",labelFor(s));trigger.setAttribute("aria-controls",trigger.id+"-options");
 const value=document.createElement("span");value.className="ss-select-value";trigger.append(value,icon("bi bi-chevron-down ss-select-chevron"));wrap.appendChild(trigger);
 if(s.id)[...document.querySelectorAll("label[for]")].filter(x=>x.htmlFor===s.id).forEach(x=>x.htmlFor=trigger.id);
 const popup=document.createElement("div");popup.className="ss-dropdown";popup.hidden=true;popup.setAttribute("role","dialog");popup.setAttribute("aria-label","قائمة الاختيارات");
 const searchRow=document.createElement("div");searchRow.className="ss-search-row";searchRow.appendChild(icon("bi bi-search"));
 const search=document.createElement("input");search.type="search";search.className="ss-search-input";search.autocomplete="off";search.spellcheck=false;search.placeholder="ابحث في القائمة...";search.setAttribute("aria-label","بحث فوري في الاختيارات");searchRow.appendChild(search);
 const results=document.createElement("div");results.className="ss-results";results.id=trigger.id+"-options";results.setAttribute("role","listbox");popup.append(searchRow,results);document.body.appendChild(popup);
 const inst={select:s,wrap,trigger,value,popup,search,results,required:s.dataset.ssRequired==="1",position:null,open:null};instances.set(s,inst);
 function update(){
  const opt=selected(s),txt=opt?optText(opt):"";
  value.textContent=txt||s.dataset.ssPlaceholder||"اختر...";value.classList.toggle("ss-select-placeholder",!s.value);trigger.disabled=s.disabled;
  trigger.classList.toggle("is-invalid",s.dataset.ssInvalid==="1");trigger.setAttribute("aria-required",inst.required?"true":"false");trigger.setAttribute("aria-invalid",s.dataset.ssInvalid==="1"?"true":"false");
  if(opened===inst)render();
 }
 function render(){
  const q=norm(search.value),opts=[...s.options].filter(o=>!o.hidden&&(!q||norm(optText(o)+" "+(o.dataset.search||"")+" "+o.value).includes(q)));
  results.replaceChildren();
  if(!opts.length){const e=document.createElement("div");e.className="ss-empty";e.textContent="لا توجد نتائج مطابقة";results.append(e);return;}
  opts.forEach(o=>{
   const b=document.createElement("button");b.type="button";b.className="ss-option";b.setAttribute("role","option");b.setAttribute("aria-selected",o.value===s.value?"true":"false");b.disabled=o.disabled;
   const txt=document.createElement("span");txt.className="ss-option-label";txt.textContent=optText(o)||"—";b.append(txt);if(o.value===s.value)b.append(icon("bi bi-check2 ss-option-check"));
   b.addEventListener("click",()=>{if(o.disabled)return;s.value=o.value;s.dataset.ssInvalid="0";update();close(inst,false);s.dispatchEvent(new Event("input",{bubbles:true}));s.dispatchEvent(new Event("change",{bubbles:true}));});
   results.append(b);
  });
 }
 function position(){
  if(popup.hidden)return;
  const r=trigger.getBoundingClientRect(),margin=10,w=Math.min(r.width,innerWidth-margin*2);
  const right=Math.max(margin,Math.min(innerWidth-r.right,innerWidth-w-margin)),below=Math.max(0,innerHeight-r.bottom-12),above=Math.max(0,r.top-12);
  const up=below<185&&above>below,room=Math.max(135,Math.min(330,up?above:below));
  popup.style.width=w+"px";popup.style.right=right+"px";popup.style.left="auto";popup.style.maxHeight=room+"px";results.style.maxHeight=Math.max(85,room-63)+"px";
  popup.style.top=(up?Math.max(8,r.top-Math.min(room,popup.offsetHeight||room)-5):r.bottom+5)+"px";
 }
 inst.position=position;
 function open(){
  if(s.disabled)return;if(opened&&opened!==inst)close(opened,false);
  opened=inst;popup.hidden=false;trigger.setAttribute("aria-expanded","true");search.value="";render();position();
  window.addEventListener("resize",position);window.addEventListener("scroll",position,true);
  requestAnimationFrame(()=>{position();search.focus({preventScroll:true});});
 }
 inst.open=open;
 trigger.addEventListener("click",()=>opened===inst?close(inst,true):open());
 search.addEventListener("input",render);
 search.addEventListener("keydown",e=>{if(e.key==="Escape"){e.preventDefault();close(inst,true);}else if(e.key==="ArrowDown"){e.preventDefault();results.querySelector(".ss-option:not(:disabled)")?.focus();}else if(e.key==="Enter"){const first=results.querySelector(".ss-option:not(:disabled)");if(first){e.preventDefault();first.click();}}});
 results.addEventListener("keydown",e=>{
  const btns=[...results.querySelectorAll(".ss-option:not(:disabled)")],i=btns.indexOf(document.activeElement);
  if(e.key==="Escape"){e.preventDefault();close(inst,true);}else if(e.key==="ArrowDown"){e.preventDefault();btns[Math.min(btns.length-1,i+1)]?.focus();}else if(e.key==="ArrowUp"){e.preventDefault();i<=0?search.focus():btns[i-1]?.focus();}else if(e.key==="Enter"&&document.activeElement?.matches(".ss-option")){e.preventDefault();document.activeElement.click();}
 });
 s.addEventListener("change",()=>{s.dataset.ssInvalid="0";update();});s.addEventListener("focus",()=>trigger.focus());update();
 if(s.form&&!forms.has(s.form)){
  const form=s.form;forms.add(form);
  form.addEventListener("submit",e=>{
   const bad=[...form.querySelectorAll("select[data-ss-ready='1'][data-ss-required='1']")].find(x=>!x.disabled&&!x.value);
   if(!bad)return;e.preventDefault();bad.dataset.ssInvalid="1";const x=instances.get(bad);x?.trigger.classList.add("is-invalid");
   if(x){if(opened&&opened!==x)close(opened,false);x.open();}x?.trigger.focus({preventScroll:true});
  });
  form.addEventListener("reset",()=>setTimeout(()=>[...form.querySelectorAll("select[data-ss-ready='1']")].forEach(x=>{x.dataset.ssInvalid="0";instances.get(x)?.trigger.classList.remove("is-invalid");x.dispatchEvent(new Event("change",{bubbles:true}));}),0));
 }
}
document.addEventListener("click",e=>{if(opened&&!opened.wrap.contains(e.target)&&!opened.popup.contains(e.target))close(opened,false);});
document.addEventListener("keydown",e=>{if(e.key==="Escape"&&opened){e.preventDefault();close(opened,true);}});
function scan(root){if(!root)return;if(root.matches?.(selector))setup(root);root.querySelectorAll?.(selector).forEach(setup);}
window.focusSearchableSelect=function(input){const s=typeof input==="string"?document.getElementById(input):input,x=s?instances.get(s):null;x?x.trigger.focus({preventScroll:true}):s?.focus?.({preventScroll:true});};
window.refreshSearchableSelect=function(input){const s=typeof input==="string"?document.getElementById(input):input;if(s instanceof HTMLSelectElement&&s.matches(selector)&&!instances.has(s))setup(s);const x=s?instances.get(s):null;if(x){x.trigger.disabled=s.disabled;x.trigger.setAttribute("aria-label",labelFor(s));x.value.textContent=optText(selected(s))||s.dataset.ssPlaceholder||"اختر...";x.value.classList.toggle("ss-select-placeholder",!s.value);}};
scan(document);
const observer=new MutationObserver(items=>items.forEach(m=>m.addedNodes.forEach(n=>{if(n.nodeType===1)scan(n);})));
if(document.body)observer.observe(document.body,{childList:true,subtree:true});else document.addEventListener("DOMContentLoaded",()=>observer.observe(document.body,{childList:true,subtree:true}));
})();