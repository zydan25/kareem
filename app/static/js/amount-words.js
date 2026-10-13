(()=>{"use strict";
const dm={"٠":"0","١":"1","٢":"2","٣":"3","٤":"4","٥":"5","٦":"6","٧":"7","٨":"8","٩":"9","۰":"0","۱":"1","۲":"2","۳":"3","۴":"4","۵":"5","۶":"6","۷":"7","۸":"8","۹":"9"};
const norm=v=>String(v||"").replace(/[٠-٩۰-۹]/g,ch=>dm[ch]).replace(/[٬,\s]/g,"").replace(/٫/g,".");
function clean(v){let s=norm(v).replace(/[^0-9.]/g,""),i=s.indexOf(".");if(i>=0)s=s.slice(0,i+1)+s.slice(i+1).replace(/\./g,"");let p=s.split(".");p[0]=(p[0]||"").replace(/^0+(?=\d)/,"");if(p.length>1)p[1]=p[1].slice(0,2);return p.length>1?p[0]+"."+p[1]:p[0];}
const ones=["صفر","واحد","اثنان","ثلاثة","أربعة","خمسة","ستة","سبعة","ثمانية","تسعة"];
const teens=["عشرة","أحد عشر","اثنا عشر","ثلاثة عشر","أربعة عشر","خمسة عشر","ستة عشر","سبعة عشر","ثمانية عشر","تسعة عشر"];
const tens=["","","عشرون","ثلاثون","أربعون","خمسون","ستون","سبعون","ثمانون","تسعون"];
const hundreds=["","مائة","مائتان","ثلاثمائة","أربعمائة","خمسمائة","ستمائة","سبعمائة","ثمانمائة","تسعمائة"];
function under100(n){if(n<10)return ones[n];if(n<20)return teens[n-10];const u=n%10,t=Math.floor(n/10);return u?ones[u]+" و"+tens[t]:tens[t];}
function under1000(n){const h=Math.floor(n/100),r=n%100;return [hundreds[h],r?under100(r):""].filter(Boolean).join(" و");}
function scaled(n,s){if(n===1)return s.one;if(n===2)return s.two;if(n>=3&&n<=10)return under1000(n)+" "+s.plural;return under1000(n)+" "+s.accusative;}
function numberWords(n){n=Math.floor(n);if(!Number.isFinite(n)||n<0||n>999999999999)return "";if(n===0)return "صفر";let rest=n,out=[];const scales=[{v:1e9,one:"مليار",two:"ملياران",plural:"مليارات",accusative:"مليارًا"},{v:1e6,one:"مليون",two:"مليونان",plural:"ملايين",accusative:"مليونًا"},{v:1e3,one:"ألف",two:"ألفان",plural:"آلاف",accusative:"ألفًا"}];for(const s of scales){const group=Math.floor(rest/s.v);rest%=s.v;if(group)out.push(scaled(group,s));}if(rest)out.push(under1000(rest));return out.join(" و");}
function update(input){const target=document.getElementById(input.dataset.wordsTarget||"");if(!target)return;const raw=clean(input.value);if(input.value!==raw)input.value=raw;const value=Number(raw);if(!raw||!Number.isFinite(value)||value<=0||value>999999999999.99){target.textContent="";target.classList.remove("has-words");return;}const whole=Math.floor(value+1e-8),fraction=Math.round((value-whole)*100),currency=input.dataset.currency||"";let text="كتابةً: "+numberWords(whole)+(currency?" "+currency:"")+" فقط لا غير";if(fraction)text+="، و"+numberWords(fraction)+" من مائة";target.textContent=text;target.classList.add("has-words");}
function handle(event){const el=event.target;if(el instanceof HTMLInputElement&&el.classList.contains("amount-words-input"))update(el);}
document.addEventListener("input",handle,true);document.addEventListener("change",handle,true);document.addEventListener("DOMContentLoaded",()=>document.querySelectorAll(".amount-words-input").forEach(update));
})();