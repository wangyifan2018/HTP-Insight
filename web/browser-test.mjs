import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const data = resolve(process.env.HTP_INSIGHT_DATA || resolve(root, 'runs'));
const screenshots = resolve(data, 'verification');
const base = process.env.HTP_INSIGHT_WEB || 'http://127.0.0.1:8000';
const demo = JSON.parse(readFileSync(resolve(data, 'demo.json'), 'utf8'));
const macChrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const executablePath = process.env.CHROME_BIN || (existsSync(macChrome) ? macChrome : undefined);
mkdirSync(screenshots, {recursive:true});
const browser = await chromium.launch({executablePath, headless:true});
const version = browser.version();
const page = await browser.newPage({viewport:{width:1440,height:960},acceptDownloads:true});
const errors = [];
page.on('pageerror', error => errors.push(error.message));
page.on('response', response => { if (response.status() >= 400) errors.push(response.status() + ' ' + response.url()); });
const checked = [];
try {
  const profileResponse = await page.request.get(base + '/api/profiles/' + demo.baseline);
  assert.ok(profileResponse.ok());
  const profile = await profileResponse.json();
  const baseline = new URLSearchParams({view:'graph',profile:demo.baseline});
  await page.goto(base + '/?' + baseline);
  await page.getByRole('heading', {name:'Graph Explorer'}).waitFor();
  await page.getByText('Top measured module', {exact:true}).waitFor();
  const locate = page.getByRole('button', {name:'Locate in timeline'});
  await locate.waitFor();
  await page.screenshot({path:resolve(screenshots,'graph.png'), fullPage:true});
  const picked = await page.locator('.graph-node.selected').getAttribute('data-node');
  await locate.click();
  await page.getByRole('heading', {name:'Profile Timeline'}).waitFor();
  const highlighted = page.locator('.track-bars button.active');
  await highlighted.waitFor();
  const event = await highlighted.getAttribute('data-event');
  const matching = profile.events.find(row => row.id === event);
  assert.ok(matching);
  assert.ok(profile.mappings.some(mapping => mapping.operation_ids.includes(matching.operation) && mapping.node_ids.includes(picked)));
  await page.screenshot({path:resolve(screenshots,'timeline.png'), fullPage:true});
  const next = page.locator('.event-list tbody tr:not(.current) button').first();
  await next.click();
  const returnLink = page.getByRole('button', {name:/Locate n[0-9]+ in graph/}).first();
  await returnLink.waitFor();
  const targetNode = (await returnLink.textContent()).match(/Locate (n\d+) /)[1];
  await returnLink.click();
  await page.locator(`.graph-node.selected[data-node="${targetNode}"]`).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('node'), targetNode);
  checked.push({check:'Graph → Timeline → Graph', model:profile.model_id, initial_node:picked, event, return_node:targetNode});
  const diagnosis = new URLSearchParams({view:'diagnosis',profile:demo.baseline,experiment:demo.id});
  await page.goto(base + '/?' + diagnosis);
  await page.getByText('Output validation', {exact:true}).waitFor();
  await page.getByText('Passed', {exact:true}).waitFor();
  await page.getByText('Optimization hypothesis', {exact:true}).waitFor();
  await page.screenshot({path:resolve(screenshots,'diagnosis.png'), fullPage:true});
  for (const format of ['Markdown','JSON']) {
    const downloadEvent = page.waitForEvent('download');
    await page.getByRole('link', {name:format, exact:true}).click();
    const download = await downloadEvent;
    checked.push({check:format + ' export', filename:download.suggestedFilename()});
  }
  const catalog = await (await page.request.get(base + '/api/catalog')).json();
  const mobile = catalog.models.find(model => model.name === 'Qualcomm MobileNet-v2 · w8a8');
  if (mobile) {
    const ort = catalog.profiles.find(profile => profile.model_id === mobile.id && profile.source === 'ORT');
    await page.goto(base + '/?' + new URLSearchParams({view:'graph',model:mobile.id,...(ort ? {profile:ort.id} : {})}));
    await page.getByText('Quantization records', {exact:true}).waitFor();
    await page.getByText('QDQ', {exact:true}).waitFor();
    await page.getByRole('button', {name:'Locate in timeline'}).waitFor();
    await page.screenshot({path:resolve(screenshots,'mobile-qdq.png'), fullPage:true});
    checked.push({check:'Qualcomm MobileNet-v2 W8A8 QDQ', model:mobile.id});
  }
  const aimet = catalog.models.find(model => model.name === 'Tiny Transformer · AIMET Encodings');
  if (aimet) {
    await page.goto(base + '/?' + new URLSearchParams({view:'graph',model:aimet.id}));
    await page.getByText('Quantization records', {exact:true}).waitFor();
    await page.getByText('AIMET', {exact:true}).waitFor();
    checked.push({check:'Tiny Transformer AIMET Encodings', model:aimet.id});
  }
  const htp = catalog.profiles.find(profile => profile.conditions.adapter === 'qnn-linting-chrome-v2.50');
  if (htp) {
    const ranking = await (await page.request.get(base + '/api/profiles/' + htp.id + '/hotspots?level=node')).json();
    const top = ranking.hotspots[0];
    const explanation = await (await page.request.get(base + '/api/profiles/' + htp.id + '/hotspots/' + encodeURIComponent(top.id) + '?level=node')).json();
    assert.equal(top.unit, 'cycles');
    assert.equal(top.total_us, null);
    await page.goto(base + '/?' + new URLSearchParams({view:'diagnosis',profile:htp.id,level:'node'}));
    await page.getByText('Sum of foreground operation cycles', {exact:false}).waitFor();
    await page.getByRole('button').filter({hasText:top.label}).waitFor();
    await page.getByRole('button', {name:'Open trace evidence'}).waitFor();
    await page.screenshot({path:resolve(screenshots,'android-htp-hotspots.png'), fullPage:true});
    await page.getByRole('button', {name:'Open trace evidence'}).click();
    await page.getByRole('heading', {name:'Profile Timeline'}).waitFor();
    await page.getByText('Foreground operations', {exact:true}).waitFor();
    const resource = explanation.example_evidence.resource;
    if (resource) {
      await page.getByText('Resources', {exact:true}).waitFor();
      await page.getByText(resource, {exact:true}).waitFor();
    }
    const event = await page.locator('.track-bars button.active').getAttribute('data-event');
    assert.equal(event, explanation.example_evidence.id);
    await page.screenshot({path:resolve(screenshots,'android-htp-timeline.png'), fullPage:true});
    checked.push({check:'Android QNN HTP linting cycles and hardware resources', profile:htp.id, event});
  }
  const capture = catalog.profiles.find(profile => profile.raw_format === 'csv' && profile.latency_us);
  if (capture) {
    await page.goto(base + '/?' + new URLSearchParams({view:'timeline',profile:capture.id}));
    await page.getByText('QAIRT Profile Records', {exact:true}).waitFor();
    await page.getByText('Message timestamp', {exact:true}).waitFor();
    await page.getByRole('link', {name:'Raw CSV'}).waitFor();
    const data = await (await page.request.get(base + '/api/profiles/' + capture.id)).json();
    const sample = data.events.find(event => event.kind === 'inference');
    assert.equal(sample.start, null);
    const response = await page.request.get(base + '/api/profiles/' + capture.id + '/events/' + sample.id);
    assert.equal((await response.json()).raw[1], 'EXECUTE');
    await page.screenshot({path:resolve(screenshots,'qnn-csv-records.png'), fullPage:true});
    checked.push({check:'QAIRT CSV graph timings and original records', profile:capture.id});
  }
  const detailed = catalog.profiles.find(profile => profile.conditions.adapter === 'qnn-viewer-csv-v2.50' && profile.conditions.profiling_level === 'detailed');
  if (detailed) {
    const profile = await (await page.request.get(base + '/api/profiles/' + detailed.id)).json();
    const cycle = profile.events.find(event => event.kind === 'node');
    assert.equal(cycle.unit, 'cycles');
    await page.goto(base + '/?' + new URLSearchParams({view:'timeline',profile:detailed.id,event:cycle.id}));
    await page.locator('.event-list tr.current').getByRole('button', {name:cycle.name, exact:true}).waitFor();
    assert.equal(await page.getByRole('combobox', {name:'Record type'}).inputValue(), 'node');
    checked.push({check:'QAIRT Detailed operation deep link', profile:detailed.id, event:cycle.id});
  }
  const captureComparison = resolve(screenshots, 'android-runner-comparison.json');
  if (existsSync(captureComparison)) {
    const {unmatched} = JSON.parse(readFileSync(captureComparison, 'utf8'));
    const response = await page.request.get(base + '/api/experiments/' + unmatched.id);
    assert.ok(response.ok());
    assert.equal((await response.json()).latency.comparable, false);
    await page.goto(base + '/?' + new URLSearchParams({view:'diagnosis',profile:unmatched.baseline,experiment:unmatched.id}));
    await page.getByText('Matched latency change unavailable.', {exact:true}).waitFor();
    await page.getByText('profiling level · different', {exact:true}).waitFor();
    checked.push({check:'Comparison explains mismatched profiling conditions', experiment:unmatched.id});
  }
  const tinySummary = resolve(data, 'android-tiny/summary.json');
  if (existsSync(tinySummary)) {
    const tiny = JSON.parse(readFileSync(tinySummary, 'utf8'));
    const tinyProfile = tiny.variants.baseline.profile.id;
    const comparison = tiny.comparison;
    const response = await page.request.get(base + '/api/experiments/' + comparison.id);
    assert.ok(response.ok());
    assert.deepEqual((await response.json()).latency, comparison.latency);
    await page.goto(base + '/?' + new URLSearchParams({view:'diagnosis',profile:tinyProfile,experiment:comparison.id,hotspot:'attention'}));
    await page.getByText('NetRun graph execute (Basic Profile)', {exact:false}).first().waitFor();
    await page.getByText('Output validation', {exact:true}).waitFor();
    await page.getByText('Passed', {exact:true}).waitFor();
    const openEvidence = page.getByRole('button', {name:'Open trace evidence'});
    await openEvidence.waitFor();
    await page.screenshot({path:resolve(screenshots,'tiny-htp-comparison.png'), fullPage:true});
    await openEvidence.click();
    const proof = page.getByText('Compiler mapping evidence', {exact:true});
    await proof.waitFor();
    await page.getByText('Source ONNX', {exact:true}).waitFor();
    const trace = await (await page.request.get(base + '/api/profiles/' + tinyProfile)).json();
    if (trace.evidence?.length) {
      await page.getByRole('link', {name:'HTP Graph JSON'}).first().waitFor();
      await page.getByRole('link', {name:'QHAS JSON'}).first().waitFor();
      const event = await page.locator('.track-bars button.active').getAttribute('data-event');
      const evidence = await (await page.request.get(base + '/api/profiles/' + tinyProfile + '/events/' + event)).json();
      assert.ok(evidence.related_evidence.length);
      checked.push({check:'QHAS and HTP Graph attached to measured operation', profile:tinyProfile, event});
    }
    const returnToGraph = page.getByRole('button', {name:/Locate n[0-9]+ in graph/}).first();
    const node = (await returnToGraph.textContent()).match(/Locate (n\d+) /)[1];
    await page.screenshot({path:resolve(screenshots,'tiny-htp-mapping.png'), fullPage:true});
    await returnToGraph.click();
    await page.locator(`.graph-node.selected[data-node="${node}"]`).waitFor();
    checked.push({check:'Tiny Transformer W8A16 HTP A/B and Attention mapping', profile:tinyProfile, experiment:comparison.id, node});
  }
  assert.deepEqual(errors, []);
  writeFileSync(resolve(screenshots,'browser.json'), JSON.stringify({browser:'Chromium ' + version, experiment:demo.id, checked, errors},null,2));
  console.log('Browser checks passed:', checked.map(item => item.check).join(', '));
} finally {
  await browser.close();
}
