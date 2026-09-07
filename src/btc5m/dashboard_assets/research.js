"use strict";
let researchState=null, researchComparison=null, researchSelection=null, researchKey=null, researchLoaded=0, researchRequest=0, researchPending=null;
function researchOptions(id,items,value) {
  const el=$(id), signature=JSON.stringify(items);
  if(el.dataset.options!==signature){el.replaceChildren(...items.map(([v,label])=>{const opt=node("option","",label);opt.value=v;return opt;}));el.dataset.options=signature;}
  el.value=value;
}
function researchDefault(variants,selected) {
  const p=selected.parameters, opposite={reversal:"continuation",continuation:"reversal",absorption:"flow_continuation",flow_continuation:"absorption"}[p.signal];
  return (variants.find(v=>v.ident!==selected.ident&&v.parameters.signal===opposite&&v.parameters.lookback_seconds===p.lookback_seconds&&v.parameters.signal_threshold===p.signal_threshold)
    ||variants.find(v=>v.ident!==selected.ident&&v.family==="control"&&v.parameters.mode===p.mode)
    ||variants.find(v=>v.ident!==selected.ident&&v.family==="control")||selected).ident;
}
function renderResearchControls(data,phase) {
  const variants=phase.variants;
  if(!variants.length)return;
  if(!variants.some(v=>v.ident===labSelection))labSelection=variants[0].ident;
  const selected=variants.find(v=>v.ident===labSelection);
  if(researchSelection!==labSelection||!variants.some(v=>v.ident===researchComparison))researchComparison=researchDefault(variants,selected);
  researchSelection=labSelection;
  const options=variants.map(v=>[v.ident,v.label]);
  researchOptions("research-selected",options,labSelection);researchOptions("research-comparison",options,researchComparison);
  researchOptions("research-phase",data.phases.map(p=>[p.id,p.kind==="exploratory"?"Exploration":"Later-data test · "+dateTime(p.start_ms)]),labPhase);
  refreshResearch();
}
function refreshResearch(force=false) {
  if(view!=="lab"||labSection!=="research"||!labSelection||!researchComparison)return;
  const params=new URLSearchParams({suite:labSuite,phase:labPhase,selected:labSelection,comparison:researchComparison,cohort:$("research-cohort").value});
  const key=params.toString();
  if(!force&&key===researchKey&&(Date.now()-researchLoaded<15000||researchPending)){if(researchState)renderResearch();return;}
  if(researchPending)researchPending.abort();
  const request=++researchRequest, changed=key!==researchKey;
  researchKey=key;researchPending=new AbortController();
  const controller=researchPending, timeout=setTimeout(()=>controller.abort(new Error("Research request timed out. Retrying on the next refresh.")),15000);
  $("research-export").disabled=true;
  if(changed){researchState=null;$("research-error").hidden=true;$("research-title").textContent="Strategy comparison";$("research-conclusion").textContent="Reading the selected recorded results…";for(const id of ["research-scope","research-cost-note","research-match-note","research-metrics","research-round-chart","research-hour-chart","research-hours","research-outliers","research-costs","research-groups","research-matched","research-compare-chart","research-parameters","research-blocks","research-best","research-worst"])clear(id);}
  fetch("/api/research?"+key,{cache:"no-store",signal:researchPending.signal}).then(async response=>{
    if(!response.ok)throw Error("Research results are unavailable for this selection. The trading studies continue independently.");
    return response.json();
  }).then(data=>{
    if(request!==researchRequest)return;
    researchState=data;researchLoaded=Date.now();$("research-error").hidden=true;$("research-export").disabled=false;renderResearch();
  }).catch(error=>{
    if(request!==researchRequest||error.name==="AbortError")return;
    $("research-error").hidden=false;$("research-error").textContent=error.message;$("research-scope").textContent="Saved analysis may be stale; no trade results have been reset.";
  }).finally(()=>{clearTimeout(timeout);if(request===researchRequest)researchPending=null;});
}
function researchBars(id,points,note) {
  if(!points.length)return empty(clear(id),"No completed results in this cohort",note);
  const values=points.map(p=>Number(p.value)), stamps=points.map(p=>p.at_ms);
  const f=chartFrame(id,Math.min(0,...values),Math.max(0,...values),[stamps[0]-150000,stamps.at(-1)+150000],money);
  f.svg.append(svgNode("line",{x1:f.x(stamps[0]-150000),x2:f.x(stamps.at(-1)+150000),y1:f.y(0),y2:f.y(0),class:"lab-diagonal"}));
  const width=Math.min(20,Math.max(2,(f.x(stamps.at(-1)+150000)-f.x(stamps[0]-150000))/(points.length*1.5)));
  for(const p of points){const value=Number(p.value),y=f.y(value),zero=f.y(0);const rect=svgNode("rect",{x:f.x(p.at_ms)-width/2,y:Math.min(y,zero),width,height:Math.max(1,Math.abs(y-zero)),fill:value>=0?"#4cdbb4":"#f07882"});rect.append(svgNode("title",{},dateTime(p.at_ms)+" · "+money(p.value)+(p.flagged?" · flagged":"")));f.svg.append(rect);}
}
function researchComparisonChart(data) {
  const rows=data.matched.series;
  if(!rows.length)return empty(clear("research-compare-chart"),"No jointly comparable rounds","Missing and incomplete rounds are excluded from both sides.");
  let a=0,b=0;
  const points=rows.map(r=>[r.at_ms,a+=Number(r.selected),b+=Number(r.comparison)]),values=points.flatMap(p=>p.slice(1));
  const f=chartFrame("research-compare-chart",Math.min(0,...values),Math.max(0,...values),[points[0][0]-150000,points.at(-1)[0]+150000],money);
  for(const [col,color,label] of [[1,"#4cdbb4",data.selected.label],[2,"#7ba9f3",data.comparison.label]]){
    let path="",last=null;
    for(const p of points){path+=(last===null||p[0]-last>300000?"M":"L")+" "+f.x(p[0])+" "+f.y(p[col])+" ";last=p[0];const dot=svgNode("circle",{cx:f.x(p[0]),cy:f.y(p[col]),r:2,fill:color});dot.append(svgNode("title",{},dateTime(p[0])+" · "+label+" · "+money(p[col])));f.svg.append(dot);}
    const line=svgNode("path",{d:path,class:"plotline",stroke:color});line.append(svgNode("title",{},label));f.svg.append(line);
  }
}
function renderResearchGroup() {
  if(!researchState)return;
  const groups=researchState.selected.groups[$("research-group").value]||[];
  labTable("research-groups",["Condition","Completed rounds","Net profit","Mean / round","Win rate","Flagged rounds"],groups.map(g=>[g.label,count(g.rounds),money(g.net),money(g.mean),labPercent(g.win_rate),count(g.flagged_rounds)]));
}
function renderResearch() {
  if(!researchState||labSection!=="research")return;
  const d=researchState,a=d.selected,b=d.comparison,s=a.stats,c=a.counts,m=d.matched;
  $("research-title").textContent=a.label;
  const outlier=number(s.without_best_3);
  $("research-conclusion").textContent=!s.rounds?"No completed capital-used rounds match this cohort. "+(d.cohort==="unflagged"?"Try All recorded to inspect the excluded results.":"Choose another strategy, or wait for its held positions to finish."):money(s.net)+" net across "+s.rounds+" completed markets; the typical (median) result is "+money(s.median)+". "+(outlier===null?"There are too few results for the remove-three-winners check. ":"After removing up to three biggest winning rounds: "+money(outlier)+". "+(Number(s.net)>0&&outlier<=0?"The recorded profit depends on those wins. ":""))+s.flagged_rounds+" included rounds carry execution-data flags. These are exploratory comparisons, not a profitability verdict.";
  const cut=Math.min(...d.clocks.map(x=>x.window_end_ms));
  $("research-scope").textContent=(d.phase_kind==="holdout"?"REGISTERED LATER-DATA TEST":"EXPLORATION")+" · "+d.trial_count+" registered variants · ended markets from "+dateTime(d.clocks[0].window_start_ms)+" through "+dateTime(Math.floor(cut/300000)*300000)+" · "+(d.cohort==="all"?"includes flagged completed rounds":"unflagged subset; earlier trades still influenced cash and limits")+". "+c.incomplete_used+" incomplete capital-used rounds excluded; "+c.flagged_used+" recorded capital-used rounds flagged. Results can update as settlement completes. Analysis updated "+dateTime(d.generated_ms)+".";
  labMetrics("research-metrics",[
    ["NET PROFIT / COMPLETED ROUND",money(s.mean),s.rounds+" markets with capital used"],
    ["WIN RATE",labPercent(s.win_rate),s.wins+" wins · "+s.losses+" losses · "+s.flat+" flat"],
    ["AVERAGE WIN / LOSS",money(s.average_win)+" / "+money(s.average_loss),"After recorded fees"],
    ["PROFIT FACTOR",labNumber(s.profit_factor,2),"Winning dollars / losing dollars · undefined with no losses"],
  ]);
  researchBars("research-round-chart",a.rounds.map(r=>({at_ms:r.start_ms,value:r.net,flagged:r.uncertain})),"One observation per capital-used market.");
  researchBars("research-hour-chart",a.hourly.filter(h=>h.used_rounds).map(h=>({at_ms:h.at_ms,value:h.net,flagged:h.flagged_rounds>0})),"No hours with completed results.");
  labTable("research-hours",["Opening hour UTC","Net profit","Completed","Excluded capital-used","Observed slots / 12"],a.hourly.map(h=>[dateTime(h.at_ms),money(h.net),count(h.used_rounds),count(h.excluded_used),count(h.observed_slots)+" / 12"]));
  labTable("research-outliers",["Sample","Net profit"],[["All selected completed rounds",money(s.net)],["Without largest winning round",money(s.without_best_1)],["Without up to three largest wins",money(s.without_best_3)],["Largest win's share of all winning dollars",labPercent(s.best_win_share)],["Median completed round",money(s.median)]]);
  labTable("research-costs",["Cost assumption","Profit"],[["Before recorded fees",money(s.before_fees)],["After recorded fees ("+money(s.fees)+")",money(s.net)],...s.cost_stress.slice(1).map(x=>["Extra "+labNumber(Number(x.extra_per_share)*100,2)+"¢ per filled share",money(x.net)])]);
  $("research-cost-note").textContent="Additional costs apply to every bought and sold share, keeping the recorded fills and strategy unchanged. This does not simulate changed liquidity, queue priority, cash constraints or gas. "+(number(s.cost_headroom_per_share)!==null?"The recorded break-even extra cost is "+labNumber(Number(s.cost_headroom_per_share)*100,2)+"¢ per executed share.":"There is no measured positive extra-cost margin for this sample.");
  renderResearchGroup();
  labMetrics("research-matched",[
    ["SELECTED · SAME MARKETS",money(m.selected_net),a.label],
    ["COMPARISON · SAME MARKETS",money(m.comparison_net),b.label],
    ["NET DIFFERENCE",money(m.difference),m.matched_rounds+" matched market rounds"],
    ["OVERLAP WHEN EITHER TRADED",labPercent(m.common_used_fraction),m.both_used+" both used capital · "+m.selected_only+" selected only · "+m.comparison_only+" comparison only"],
  ]);
  researchComparisonChart(d);
  $("research-match-note").textContent="Green: "+a.label+"; blue: "+b.label+". Cumulative profit uses only the same comparable market rounds, including "+m.both_flat+" where both stayed flat. "+m.excluded_rounds+" unmatched, missing, flagged (if filtered), or unfinished rounds are excluded. Lines break at missing rounds. Profit correlation when either used capital: "+labNumber(m.active_round_correlation,2)+". Overlap/correlation describe shared evidence, not independent strategies or a combined portfolio.";
  labTable("research-parameters",["Displayed parameter difference","Selected","Comparison"],d.parameter_differences.map(p=>[human(p.parameter),String(p.selected??"—"),String(p.comparison??"—")]),"Displayed parameters match; check the full registered definitions before calling this a controlled ablation");
  const blocks=[...a.block_sensitivity.map(x=>({...x,series:"Selected"})),...m.block_sensitivity.map(x=>({...x,series:"Selected minus comparison"}))];
  labTable("research-blocks",["Quantity","Block size","Complete blocks","Included / available rounds","Mean / round","Descriptive 95% range"],blocks.map(x=>[x.series,x.minutes+" min",count(x.complete_blocks),x.included_rounds+" / "+x.available_rounds,money(x.mean_per_round),x.interval95?money(x.interval95[0])+" to "+money(x.interval95[1]):human(x.status)]));
  for(const [id,rows] of [["research-best",a.best_rounds.filter(r=>Number(r.net)>0)],["research-worst",a.worst_rounds.filter(r=>Number(r.net)<0)]])labTable(id,["Market opening UTC","Net profit","First entry","Flagged"],rows.map(r=>[dateTime(r.start_ms),money(r.net),quotePrice(r.entry_price),r.uncertain?"Yes":"No"]));
}
for(const button of document.querySelectorAll("[data-lab-section]"))button.addEventListener("click",()=>{
  labSection=button.dataset.labSection;
  for(const b of document.querySelectorAll("[data-lab-section]")){const selected=b===button;b.classList.toggle("selected",selected);b.setAttribute("aria-pressed",String(selected));}
  renderLab();
});
$("research-selected").addEventListener("change",()=>{labSelection=$("research-selected").value;renderLab();});
$("research-comparison").addEventListener("change",()=>{researchComparison=$("research-comparison").value;refreshResearch(true);});
$("research-phase").addEventListener("change",()=>{labPhase=$("research-phase").value;labSelection=null;renderLab();});
$("research-cohort").addEventListener("change",()=>refreshResearch(true));
$("research-group").addEventListener("change",renderResearchGroup);
$("research-export").addEventListener("click",()=>{
  if(!researchState)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(researchState,null,2)],{type:"application/json"}));
  const link=node("a");link.href=url;link.download="btc5m-strategy-research.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
window.addEventListener("resize",()=>{if(view==="lab")renderResearch();});
