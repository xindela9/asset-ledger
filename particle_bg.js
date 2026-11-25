// 粒子连线网络背景
(function(){
  var canvas = document.createElement('canvas');
  canvas.id = 'particleBg';
  canvas.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1;pointer-events:none;';
  document.body.appendChild(canvas);

  var ctx = canvas.getContext('2d');
  var particles = [];
  var PARTICLE_COUNT = 60;
  var LINK_DIST = 150;
  var SPEED = 0.4;

  function resize(){
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  // 获取主题色
  function getBrandColor(){
    var s = getComputedStyle(document.documentElement);
    var c = s.getPropertyValue('--brand').trim();
    if(!c) c = '#56ab2f';
    return c;
  }

  function hexToRgb(hex){
    hex = hex.replace('#','');
    if(hex.length===3) hex = hex[0]+hex[0]+hex[1]+hex[1]+hex[2]+hex[2];
    var n = parseInt(hex,16);
    return {r:(n>>16)&255, g:(n>>8)&255, b:n&255};
  }

  function init(){
    particles = [];
    for(var i=0; i<PARTICLE_COUNT; i++){
      particles.push({
        x: Math.random()*canvas.width,
        y: Math.random()*canvas.height,
        vx: (Math.random()-0.5)*SPEED,
        vy: (Math.random()-0.5)*SPEED,
        r: Math.random()*2+1
      });
    }
  }
  init();

  function draw(){
    ctx.clearRect(0,0,canvas.width,canvas.height);
    var rgb = hexToRgb(getBrandColor());

    // 画连线
    for(var i=0; i<particles.length; i++){
      for(var j=i+1; j<particles.length; j++){
        var dx = particles[i].x - particles[j].x;
        var dy = particles[i].y - particles[j].y;
        var dist = Math.sqrt(dx*dx+dy*dy);
        if(dist < LINK_DIST){
          var alpha = (1 - dist/LINK_DIST) * 0.25;
          ctx.beginPath();
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.strokeStyle = 'rgba('+rgb.r+','+rgb.g+','+rgb.b+','+alpha+')';
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      }
    }

    // 画粒子
    for(var i=0; i<particles.length; i++){
      var p = particles[i];
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI*2);
      ctx.fillStyle = 'rgba('+rgb.r+','+rgb.g+','+rgb.b+',0.35)';
      ctx.fill();

      // 移动
      p.x += p.vx;
      p.y += p.vy;

      // 边界反弹
      if(p.x < 0 || p.x > canvas.width) p.vx *= -1;
      if(p.y < 0 || p.y > canvas.height) p.vy *= -1;
    }

    requestAnimationFrame(draw);
  }
  draw();
})();
