// --- Sample data provided by user ---
const sample = {
  hr_bpm: 90,
  spo2_pct: 98.8,
  skin_temp: 33.7,
  bloodpressure_systolic: 120,
  bp_diastolic: 78,
  altitude: 300,
  latitude: 27.71,
  longitude: 85.33,
  steps: 10000,
  past_incident_flag: 1,
  weather_condition: "Storm"
};

// utility: update UI fields
function updateUI(data){
  document.getElementById('hr').innerText = data.hr_bpm;
  document.getElementById('spo2').innerText = data.spo2_pct;
  document.getElementById('skin').innerText = data.skin_temp;
  document.getElementById('bp').innerText = data.bloodpressure_systolic + ' / ' + data.bp_diastolic;
  document.getElementById('alt').innerText = data.altitude;
  document.getElementById('steps').innerText = data.steps;
  document.getElementById('past').innerText = data.past_incident_flag ? 'Yes' : 'No';
  document.getElementById('weather').innerText = data.weather_condition;
  document.getElementById('coords').innerText = `Lat: ${data.latitude}, Lon: ${data.longitude}`;

  // set inputs
  document.getElementById('input_hr').value = data.hr_bpm;
  document.getElementById('input_spo2').value = data.spo2_pct;
  document.getElementById('input_skin').value = data.skin_temp;
  document.getElementById('input_sys').value = data.bloodpressure_systolic;
  document.getElementById('input_dia').value = data.bp_diastolic;
  document.getElementById('input_alt').value = data.altitude;
  document.getElementById('input_steps').value = data.steps;
  document.getElementById('input_inc').value = data.past_incident_flag;
  document.getElementById('input_weather').value = data.weather_condition;

  // update map marker
  if(marker){
    marker.setLatLng([data.latitude, data.longitude]);
    map.setView([data.latitude, data.longitude], 10, {animate:true});
  }
}

// --- risk calculation ---
function calculateRisk(d){
  // Normalize each metric to a 0..1 risk contribution (higher -> worse)
  const hrRisk = Math.min(Math.max((d.hr_bpm - 60) / 60, 0), 1); // 60-120 bpm
  const spo2Risk = Math.min(Math.max((100 - d.spo2_pct) / 10, 0), 1); // 90-100
  const skinRisk = Math.min(Math.max((d.skin_temp - 32) / 8, 0), 1); // 32-40
  const sysRisk = Math.min(Math.max((d.bloodpressure_systolic - 110) / 50, 0), 1); // 110-160
  const altRisk = Math.min(d.altitude / 4000, 1); // 0..4000m
  const stepsBenefit = Math.min(d.steps / 15000, 1); // more steps -> reduces risk
  const pastRisk = d.past_incident_flag ? 0.25 : 0;
  const weatherPenalty = (/(storm|rain|snow)/i.test(d.weather_condition)) ? 0.2 : 0;

  // weights (tunable)
  const w = {hr:0.18, spo2:0.22, skin:0.12, sys:0.15, alt:0.08, steps: -0.12, past:0.15, weather:0.12};

  let score = 0;
  score += hrRisk * w.hr;
  score += spo2Risk * w.spo2;
  score += skinRisk * w.skin;
  score += sysRisk * w.sys;
  score += altRisk * w.alt;
  score += stepsBenefit * w.steps; // negative reduces risk
  score += pastRisk * w.past;
  score += weatherPenalty * w.weather;

  // map to 0..100
  score = Math.max(0, Math.min(1, score));
  return Math.round(score * 100);
}

// risk level labels and colors
function riskLevel(score){
  if(score >= 75) return {level:'CRITICAL', cls:'critical', color:getComputedStyle(document.documentElement).getPropertyValue('--critical')};
  if(score >= 50) return {level:'HIGH', cls:'high', color:getComputedStyle(document.documentElement).getPropertyValue('--high')};
  if(score >= 25) return {level:'MODERATE', cls:'moderate', color:getComputedStyle(document.documentElement).getPropertyValue('--moderate')};
  return {level:'LOW', cls:'low', color:getComputedStyle(document.documentElement).getPropertyValue('--low')};
}

// produce human recommendations based on level and drivers
function produceRecommendations(d, score){
  const r = [];
  const lvl = riskLevel(score).level;
  if(lvl === 'CRITICAL'){
    r.push('Seek immediate help: stop activity, move to safe shelter (if weather).');
    r.push('If chest pain, severe breathlessness, or fainting - call emergency services.');
  } else if(lvl === 'HIGH'){
    r.push('Reduce exertion, hydrate, find shelter from severe weather.');
    r.push('Consider contacting a local healthcare provider or companion.');
  } else if(lvl === 'MODERATE'){
    r.push('Monitor symptoms closely. Take rest breaks and hydrate.');
    r.push('Avoid high-intensity exertion until metrics normalize.');
  } else {
    r.push('Low immediate risk — continue normal activities but monitor metrics.');
  }

  if(d.spo2_pct < 92) r.push('Low SpO₂ detected — descend to lower altitude and seek oxygen if possible.');
  if(d.skin_temp > 38) r.push('High skin temperature — possible fever or heat stress — cool down and rest.');
  if(d.bloodpressure_systolic > 160 || d.bp_diastolic > 100) r.push('Very high blood pressure — seek medical attention.');
  if(/storm|rain|snow/i.test(d.weather_condition)) r.push('Bad weather: take weather-appropriate precautions and postpone risky outdoor activities.');
  if(d.past_incident_flag) r.push('Past incident on record — keep monitoring and consider extra caution.');

  return r;
}

// --- chart for trends ---
const ctx = document.getElementById('trendChart').getContext('2d');
const trendChart = new Chart(ctx, {
  type:'line',
  data:{labels:[],datasets:[{label:'Risk Score',data:[],fill:true,tension:0.3}]},
  options:{plugins:{legend:{display:false}},scales:{x:{grid:{display:false}},y:{min:0,max:100}}},
});

// --- map ---
const map = L.map('map', {zoomControl:false, attributionControl:false}).setView([sample.latitude, sample.longitude], 10);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19}).addTo(map);
const marker = L.marker([sample.latitude, sample.longitude]).addTo(map);

// initial load
updateUI(sample);
let history = [];

function analyzeNow(data){
  const score = calculateRisk(data);
  const rl = riskLevel(score);

  document.getElementById('riskCircle').innerText = score;
  document.getElementById('riskCircle').style.border = `4px solid ${rl.color}`;
  document.getElementById('riskLevelText').innerText = rl.level;
  document.getElementById('riskLevelText').style.color = rl.color;

  // alerts
  const alertsEl = document.getElementById('alerts'); alertsEl.innerHTML = '';
  const a = document.createElement('div');
  a.className = `alert ${rl.cls}`;
  a.innerHTML = `<strong>${rl.level} RISK</strong>: Score ${score}`;
  alertsEl.appendChild(a);

  // detailed recommendations
  const recs = produceRecommendations(data, score);
  const recEl = document.getElementById('recommendations'); recEl.innerHTML = '';
  recs.forEach(r=>{ const li = document.createElement('li'); li.innerText = r; recEl.appendChild(li); });

  // add to trend
  history.push({t: new Date().toLocaleTimeString(), v:score});
  if(history.length > 20) history.shift();
  trendChart.data.labels = history.map(h=>h.t);
  trendChart.data.datasets[0].data = history.map(h=>h.v);
  trendChart.update();

  // visual highlight of risk circle background
  const bg = {
    low: 'linear-gradient(135deg, rgba(16,185,129,0.08), transparent)',
    moderate: 'linear-gradient(135deg, rgba(245,158,11,0.08), transparent)',
    high: 'linear-gradient(135deg, rgba(249,115,22,0.08), transparent)',
    critical: 'linear-gradient(135deg, rgba(239,68,68,0.08), transparent)'
  };
  document.getElementById('riskCircle').style.background = bg[rl.cls] || 'transparent';

  return score;
}

// wire up buttons
document.getElementById('analyzeBtn').addEventListener('click', ()=>{
  // read inputs
  const d = {
    hr_bpm: Number(document.getElementById('input_hr').value),
    spo2_pct: Number(document.getElementById('input_spo2').value),
    skin_temp: Number(document.getElementById('input_skin').value),
    bloodpressure_systolic: Number(document.getElementById('input_sys').value),
    bp_diastolic: Number(document.getElementById('input_dia').value),
    altitude: Number(document.getElementById('input_alt').value),
    latitude: sample.latitude,
    longitude: sample.longitude,
    steps: Number(document.getElementById('input_steps').value),
    past_incident_flag: Number(document.getElementById('input_inc').value),
    weather_condition: document.getElementById('input_weather').value
  };
  updateUI(d);
  analyzeNow(d);
});

document.getElementById('resetBtn').addEventListener('click', ()=>{ updateUI(sample); analyzeNow(sample); });

let simInterval = null;
document.getElementById('simulateBtn').addEventListener('click', ()=>{
  if(simInterval){ clearInterval(simInterval); simInterval = null; document.getElementById('simulateBtn').innerText = 'Simulate Live Update'; return; }
  document.getElementById('simulateBtn').innerText = 'Stop Simulation';
  simInterval = setInterval(()=>{
    // small random drift
    const d = {
      hr_bpm: Math.round(Number(document.getElementById('input_hr').value) + (Math.random()*8-4)),
      spo2_pct: Math.round((Number(document.getElementById('input_spo2').value) + (Math.random()*1-0.5))*10)/10,
      skin_temp: Math.round((Number(document.getElementById('input_skin').value) + (Math.random()*0.6-0.3))*10)/10,
      bloodpressure_systolic: Math.round(Number(document.getElementById('input_sys').value) + (Math.random()*6-3)),
      bp_diastolic: Math.round(Number(document.getElementById('input_dia').value) + (Math.random()*4-2)),
      altitude: Number(document.getElementById('input_alt').value),
      latitude: sample.latitude + (Math.random()*0.02-0.01),
      longitude: sample.longitude + (Math.random()*0.02-0.01),
      steps: Number(document.getElementById('input_steps').value) + Math.round(Math.random()*20),
      past_incident_flag: Number(document.getElementById('input_inc').value),
      weather_condition: document.getElementById('input_weather').value
    };
    updateUI(d);
    analyzeNow(d);
  }, 2500);
});

// initial analysis
analyzeNow(sample);