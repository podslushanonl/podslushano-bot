fetch('mascot.b64?v=3',{cache:'no-store'}).then(r=>r.text()).then(b64=>{const src='data:image/webp;base64,'+b64.trim();document.querySelectorAll('img.mascot').forEach(img=>img.src=src)});
const screens={home:document.getElementById('home-screen'),lesson:document.getElementById('lesson-screen'),finish:document.getElementById('finish-screen')};
const bottomNav=document.getElementById('bottom-nav');
let selectedAnswer=null;
function showScreen(name){Object.values(screens).forEach(s=>s.classList.remove('is-active'));screens[name].classList.add('is-active');bottomNav.style.display=name==='home'?'flex':'none';window.scrollTo({top:0,behavior:'instant'});}
document.getElementById('continue-button').addEventListener('click',()=>{resetLesson();showScreen('lesson')});
document.querySelectorAll('[data-go-home]').forEach(btn=>btn.addEventListener('click',()=>showScreen('home')));
const answers=[...document.querySelectorAll('.answer')];
const checkBtn=document.getElementById('check-answer');
answers.forEach(btn=>btn.addEventListener('click',()=>{if(document.querySelector('.feedback.show'))return;answers.forEach(a=>a.classList.remove('selected'));btn.classList.add('selected');selectedAnswer=btn;checkBtn.disabled=false;}));
checkBtn.addEventListener('click',()=>{if(!selectedAnswer)return;checkBtn.style.display='none';if(selectedAnswer.dataset.correct==='true'){selectedAnswer.classList.add('correct');document.getElementById('feedback-good').classList.add('show')}else{selectedAnswer.classList.add('wrong');document.querySelector('[data-correct="true"]').classList.add('correct');document.getElementById('feedback-bad').classList.add('show')}});
document.getElementById('next-step').addEventListener('click',()=>showScreen('finish'));
document.getElementById('try-again').addEventListener('click',resetLesson);
function resetLesson(){selectedAnswer=null;answers.forEach(a=>a.classList.remove('selected','correct','wrong'));document.querySelectorAll('.feedback').forEach(f=>f.classList.remove('show'));checkBtn.style.display='block';checkBtn.disabled=true;}
document.querySelectorAll('.bottom-nav button:not(.active)').forEach(btn=>btn.addEventListener('click',()=>alert('Этот раздел будет оформлен на следующем этапе.')));