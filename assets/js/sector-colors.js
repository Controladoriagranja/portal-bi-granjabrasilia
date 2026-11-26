/* Seletor HEX compartilhado: nenhuma dependência ou requisição de rede. */
const sectorColorPickers = new Map();
function normalizeSectorHex(value) {
  let color=String(value || '').trim();
  if (/^#?[\da-f]{3}$/i.test(color)) color='#'+color.replace('#','').split('').map(c=>c+c).join('');
  if (/^[\da-f]{6}$/i.test(color)) color='#'+color;
  if (!/^#[\da-f]{6}$/i.test(color)) throw new Error('Informe uma cor HEX válida, como #2A8FBD.');
  return color.toUpperCase();
}
function sectorHsvToHex(h,s,v) {
  const f=n=>{ const k=(n+h/60)%6; return Math.round((v-v*s*Math.max(0,Math.min(k,4-k,1)))*255).toString(16).padStart(2,'0'); };
  return ('#'+f(5)+f(3)+f(1)).toUpperCase();
}
function sectorHexToHsv(hex) {
  const [r,g,b]=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255);
  const max=Math.max(r,g,b), min=Math.min(r,g,b), d=max-min;
  let h=0;
  if(d) h=60*(max===r?((g-b)/d+6)%6:max===g?(b-r)/d+2:(r-g)/d+4);
  return {h,s:max?d/max:0,v:max};
}
function mountSectorColorPicker(id) {
  if(sectorColorPickers.has(id)) return sectorColorPickers.get(id);
  const root=document.getElementById(id);
  root.classList.add('sector-color-picker');
  root.innerHTML=`<div class="sector-color-sv" tabindex="0" role="group" aria-label="Saturação e brilho: use as setas esquerda e direita para saturação; acima e abaixo para brilho"><span class="sector-color-cursor"></span></div>
    <input type="range" class="sector-color-hue" min="0" max="360" step="1" aria-label="Matiz da cor">
    <div class="sector-color-hex-row"><input class="sector-color-hex" type="text" maxlength="7" autocomplete="off" spellcheck="false" aria-label="Cor hexadecimal" aria-describedby="${id}Error"><span class="sector-color-swatch" aria-hidden="true"></span></div>
    <span class="sector-color-error" id="${id}Error" role="status" aria-live="polite"></span>`;
  const pad=root.querySelector('.sector-color-sv'), cursor=root.querySelector('.sector-color-cursor');
  const hue=root.querySelector('.sector-color-hue'), input=root.querySelector('.sector-color-hex');
  const error=root.querySelector('.sector-color-error'), swatch=root.querySelector('.sector-color-swatch');
  let hsv={h:0,s:1,v:1};
  function paint(updateText=true) {
    const hex=sectorHsvToHex(hsv.h,hsv.s,hsv.v);
    root.style.setProperty('--picker-hue',sectorHsvToHex(hsv.h,1,1));
    cursor.style.left=(hsv.s*100)+'%';cursor.style.top=((1-hsv.v)*100)+'%';
    hue.value=hsv.h;swatch.style.background=hex;
    if(updateText) { input.value=hex; error.textContent=''; input.removeAttribute('aria-invalid'); }
  }
  function set(value) {
    const hex=normalizeSectorHex(value);hsv=sectorHexToHsv(hex);paint();
  }
  function fromText(canonicalize=false) {
    try { const hex=normalizeSectorHex(input.value);hsv=sectorHexToHsv(hex);paint(false);if(canonicalize) input.value=hex;error.textContent='';input.removeAttribute('aria-invalid'); }
    catch(e) { error.textContent=e.message;input.setAttribute('aria-invalid','true'); }
  }
  function point(event) {
    const bounds=pad.getBoundingClientRect();
    hsv.s=Math.max(0,Math.min(1,(event.clientX-bounds.left)/bounds.width));
    hsv.v=1-Math.max(0,Math.min(1,(event.clientY-bounds.top)/bounds.height));paint();
  }
  pad.addEventListener('pointerdown',event=>{ if(event.button!==0)return; pad.focus();pad.setPointerCapture(event.pointerId);point(event); });
  pad.addEventListener('pointermove',event=>{ if(pad.hasPointerCapture(event.pointerId))point(event); });
  pad.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;
    event.preventDefault();const step=event.shiftKey ? 0.1 : 0.01;
    if(event.key==='ArrowLeft')hsv.s-=step;if(event.key==='ArrowRight')hsv.s+=step;
    if(event.key==='ArrowUp')hsv.v+=step;if(event.key==='ArrowDown')hsv.v-=step;
    hsv.s=Math.max(0,Math.min(1,hsv.s));hsv.v=Math.max(0,Math.min(1,hsv.v));paint();
  });
  hue.addEventListener('input',()=>{ hsv.h=Number(hue.value);paint(); });
  input.addEventListener('input',()=>fromText());input.addEventListener('blur',()=>fromText(true));
  const picker={set,get:()=>{ try { return normalizeSectorHex(input.value); } catch(e) { fromText();input.focus();throw e; } }};
  sectorColorPickers.set(id,picker);
  set(root.dataset.initialColor || '#58a6ff');
  return picker;
}
let sectorEditCode=null;
let sectorEditBusy=false;
function openSectorEditor(code) {
  if(currentUser?.role!=='admin')return;
  const dialog=document.getElementById('sectorEditDialog');
  sectorEditCode=code;
  document.getElementById('editSectorName').value=sectorLabel(code);
  document.getElementById('editSectorError').textContent='';
  const picker=mountSectorColorPicker('editSectorColorPicker');
  try { picker.set(sectorColor(code)); }
  catch(_) { const input=document.querySelector('#editSectorColorPicker .sector-color-hex');input.value=String(sectorColor(code));input.dispatchEvent(new Event('input')); }
  dialog.showModal();document.getElementById('editSectorName').focus();
}
function closeSectorEditor() {
  if(sectorEditBusy)return;
  document.getElementById('sectorEditDialog').close();sectorEditCode=null;
}
async function saveSectorEditor(event) {
  event.preventDefault();
  if(sectorEditBusy || currentUser?.role!=='admin' || !sectorEditCode)return;
  const error=document.getElementById('editSectorError');error.textContent='';
  const name=document.getElementById('editSectorName').value.trim();
  if(!name){error.textContent='Informe o nome do setor.';return;}
  let color;
  try { color=mountSectorColorPicker('editSectorColorPicker').get(); }
  catch(e){error.textContent=e.message;return;}
  const button=document.getElementById('saveSectorEditBtn');
  sectorEditBusy=true;setButtonBusy(button,true,'Salvando...');
  try {
    const result=await portalApiRequest(`/api/admin/setores/${encodeURIComponent(sectorEditCode)}`,{method:'PATCH',body:JSON.stringify({name,color})});
    if(result?.data)applyPortalDataResponse(result.data);
    refreshAdminCrudViews();
    document.getElementById('sectorEditDialog').close();sectorEditCode=null;
    showToast('Nome e cor do setor atualizados.','success');
  } catch(e){error.textContent=e.message || 'Não foi possível salvar o setor.';}
  finally {sectorEditBusy=false;setButtonBusy(button,false);}
}
document.addEventListener('DOMContentLoaded',()=>{
  mountSectorColorPicker('newSectorColorPicker');
  document.getElementById('sectorEditDialog').addEventListener('cancel',event=>{event.preventDefault();closeSectorEditor();});
});
