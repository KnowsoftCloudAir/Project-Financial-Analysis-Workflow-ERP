(function(){
  var s=document.createElement('style');
  s.textContent='[x-cloak]{display:none!important}.angel-wave-stage,.angel-orb{transition:opacity .35s ease}';
  document.head.appendChild(s);
  window.cgAngelSay=function(t){try{if(!('speechSynthesis'in window)||!t)return;speechSynthesis.cancel();speechSynthesis.speak(new SpeechSynthesisUtterance(String(t)));}catch(e){}};
  console.log('[Angel] fix loaded');
})();
