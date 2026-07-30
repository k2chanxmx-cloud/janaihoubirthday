const cards=[...document.querySelectorAll('.photo-card')];
const promptEl=document.getElementById('prompt');
const generateBtn=document.getElementById('generateBtn');
const loading=document.getElementById('loading');
const result=document.getElementById('result');
const resultImage=document.getElementById('resultImage');
const counter=document.getElementById('counter');
const toast=document.getElementById('toast');
let selectedPhoto='';
const postText='じゃない方をAIでお祝いしてみた🎂✨\n\n#じゃない方生誕';

function validate(){generateBtn.disabled=!(selectedPhoto&&promptEl.value.trim())}
function showToast(message){toast.textContent=message;toast.classList.add('show');setTimeout(()=>toast.classList.remove('show'),2600)}
cards.forEach(card=>card.addEventListener('click',()=>{cards.forEach(x=>x.classList.remove('selected'));card.classList.add('selected');selectedPhoto=card.dataset.photo;validate()}));
promptEl.addEventListener('input',()=>{counter.textContent=`${promptEl.value.length}/200`;validate()});

generateBtn.addEventListener('click',async()=>{
  if(generateBtn.disabled)return;
  generateBtn.disabled=true;result.hidden=true;loading.hidden=false;loading.scrollIntoView({behavior:'smooth',block:'center'});
  try{
    const response=await fetch('/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({photo:selectedPhoto,prompt:promptEl.value.trim()})});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||'画像生成に失敗しました。');
    resultImage.src=data.image;document.getElementById('downloadBtn').href=data.image;
    loading.hidden=true;result.hidden=false;result.scrollIntoView({behavior:'smooth',block:'start'});
  }catch(error){loading.hidden=true;showToast(error.message);validate()}
});

async function dataUrlToFile(dataUrl){const blob=await(await fetch(dataUrl)).blob();return new File([blob],'janaihou_birthday_2026.jpg',{type:'image/jpeg'})}
document.getElementById('shareBtn').addEventListener('click',async()=>{
  try{
    const file=await dataUrlToFile(resultImage.src);
    if(navigator.canShare&&navigator.canShare({files:[file]})){
      await navigator.share({files:[file],text:postText,title:'じゃない方 生誕AIメーカー'});
    }else{
      await navigator.clipboard.writeText(postText);
      window.open(`https://twitter.com/intent/tweet?text=${encodeURIComponent(postText)}`,'_blank');
      showToast('投稿文をコピーしました。画像を保存してXに添付してください。');
    }
  }catch(error){if(error.name!=='AbortError')showToast('共有できませんでした。画像保存と投稿文コピーをご利用ください。')}
});
document.getElementById('copyBtn').addEventListener('click',async()=>{await navigator.clipboard.writeText(postText);showToast('投稿文をコピーしました！')});
document.getElementById('retryBtn').addEventListener('click',()=>{result.hidden=true;document.getElementById('photoGrid').scrollIntoView({behavior:'smooth'});validate()});
