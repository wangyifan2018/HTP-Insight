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
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], {origin:base});
  await page.emulateMedia({colorScheme:'dark'});
  await page.goto(base + '/');
  await page.getByRole('heading', {name:'Analysis workflow'}).waitFor();
  assert.deepEqual(await page.locator('.workflow-grid b').allTextContents(), ['Import', 'Profile', 'Locate', 'Diagnose', 'Optimize']);
  await page.screenshot({path:resolve(screenshots,'workspace-workflow.png'),fullPage:true});
  const workflowImport = page.locator('.workflow-grid').getByRole('button', {name:/^Import/});
  await workflowImport.click();
  const dialog = page.getByRole('dialog', {name:'Manage local evidence'});
  await dialog.waitFor();
  assert.equal(await dialog.getByLabel('Action').inputValue(), 'import_model');
  await dialog.getByRole('button', {name:'Close'}).click();
  await page.getByRole('button', {name:'System Status'}).click();
  await page.getByText('Available locally', {exact:true}).waitFor();
  await page.getByRole('heading', {name:'Linux / SSH capture'}).waitFor();
  await page.getByRole('button', {name:'Workspace', exact:true}).click();
  await page.getByRole('button', {name:/Explore (Mac ORT|ORT CPU) recording/}).click();
  await page.getByRole('heading', {name:'Performance capture'}).waitFor();
  assert.match(await page.locator('.capture-header p').textContent(), /CPUExecutionProvider.*measured/);
  await page.getByRole('button', {name:'Locate hotspots',exact:true}).click();
  await page.getByRole('heading', {name:'Locate Hotspots',exact:true}).waitFor();
  await page.getByRole('button', {name:'Diagnose hotspot'}).click();
  await page.getByText('Inferred mapping', {exact:true}).waitFor();
  await page.getByRole('button', {name:'Generate Claude Code Experiment Plan'}).click();
  const notebook = page.getByLabel('Notebook task Markdown');
  await notebook.waitFor();
  const markdown = await notebook.textContent();
  assert.match(markdown, /CPUExecutionProvider/);
  assert.match(markdown, /Numerical and A\/B acceptance/);
  await page.getByRole('button', {name:'Copy Markdown'}).click();
  await page.getByText('Markdown copied.', {exact:true}).waitFor();
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), markdown);
  for (const format of ['Markdown','JSON']) {
    const downloading = page.waitForEvent('download');
    await page.getByRole('link', {name:format,exact:true}).click();
    const downloaded = await downloading;
    const content = readFileSync(await downloaded.path(), 'utf8');
    assert.equal(format === 'Markdown' ? content : JSON.parse(content).markdown, markdown);
  }
  await page.emulateMedia({colorScheme:'light'});
  await page.screenshot({path:resolve(screenshots,'notebook-plan.png'),fullPage:true});
  checked.push({check:'Guided measured CPU workflow, capabilities, copy and both Notebook task exports'});

  const profileResponse = await page.request.get(base + '/api/profiles/' + demo.baseline);
  assert.ok(profileResponse.ok());
  const profile = await profileResponse.json();
  const baseline = new URLSearchParams({view:'graph',profile:demo.baseline});
  await page.goto(base + '/?' + baseline);
  await page.getByRole('heading', {name:'Graph Explorer'}).waitFor();
  await page.getByText('Top measured module', {exact:true}).waitFor();
  const search = page.getByRole('textbox', {name:'Search modules or operators'});
  await search.fill('not-a-real-operator');
  await page.getByText('No matching module or operator.', {exact:true}).waitFor();
  await search.fill('attention');
  await page.locator('.tree').getByText('Attention', {exact:true}).waitFor();
  await search.clear();
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
  checked.push({check:'Module search and Graph → Timeline → Graph', model:profile.model_id, initial_node:picked, event, return_node:targetNode});
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
    await page.getByRole('button', {name:'Generate Claude Code Experiment Plan'}).click();
    const plan = page.getByLabel('Notebook task Markdown');
    await plan.waitFor();
    assert.match(await plan.textContent(), /flatten batch and head/);
    assert.match(await plan.textContent(), /QNN HTP/);
    assert.match(await plan.textContent(), /e205/);
    await page.getByRole('button', {name:'Back to diagnosis'}).click();
    checked.push({check:'Android Attention task uses mapped score layout and real event evidence', profile:tinyProfile});
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
    const originalEvent = await page.locator('.track-bars button.active').getAttribute('data-event');
    await page.screenshot({path:resolve(screenshots,'tiny-htp-mapping.png'), fullPage:true});
    const htpTimeline = await (await page.request.get(base + '/api/profiles/' + tinyProfile + '/htp-timeline')).json();
    const topBlocker = htpTimeline.blockers[0];
    for (const lane of htpTimeline.lanes.filter(row => row.event_count > 0)) {
      await page.locator(`[data-lane="${lane.id}"]`).waitFor();
    }
    const typeFilter = page.getByLabel('Filter timeline by resource type');
    await typeFilter.selectOption('type:HMX');
    const hmxLanes = htpTimeline.lanes.filter(lane => lane.type === 'HMX' && lane.event_count > 0);
    assert.equal(await page.locator('.hardware-tracks [data-lane]').count(), hmxLanes.length);
    await page.getByText(/The physical engine count is unavailable/).waitFor();
    await page.locator('.parallel-row').first().click();
    await page.locator('.track-bars button.possible-blocker').waitFor();
    assert.equal(await page.locator('.track-bars button.possible-blocker').getAttribute('data-event'), topBlocker.source);
    assert.equal(await page.locator('.track-bars button.active').getAttribute('data-event'), topBlocker.target);
    await page.locator('.hardware-arrows .blocker-arrow').waitFor({state:'attached'});
    assert.equal(await typeFilter.inputValue(), '');
    await page.getByText('Operation dependencies', {exact:true}).waitFor();
    const arrows = page.getByLabel('Dependency arrows', {exact:true});
    await arrows.uncheck();
    assert.equal(await page.locator('.hardware-arrows').count(), 0);
    await arrows.check();
    await page.getByLabel('Timeline zoom', {exact:true}).selectOption('16');
    await page.locator('.track-bars button.possible-blocker').waitFor();
    const eventSearch = page.getByRole('textbox', {name:'Find timeline operation'});
    await eventSearch.fill(topBlocker.target);
    assert.equal(await page.locator('.event-list tbody tr').count(), 1);
    await eventSearch.clear();
    await page.screenshot({path:resolve(screenshots,'htp-parallelism.png'), fullPage:true});
    checked.push({check:'QAIRT execution lane filtering, dependencies and cross-lane blocker highlight', profile:tinyProfile, source:topBlocker.source, target:topBlocker.target});
    await page.goto(base + '/?' + new URLSearchParams({view:'timeline',profile:tinyProfile,node,event:originalEvent}));
    await returnToGraph.waitFor();
    await returnToGraph.click();
    await page.locator(`.graph-node.selected[data-node="${node}"]`).waitFor();
    checked.push({check:'Tiny Transformer W8A16 HTP A/B and Attention mapping', profile:tinyProfile, experiment:comparison.id, node});
  }
  const resourceProfile = process.env.HTP_INSIGHT_BROWSER_RESOURCE_PROFILE;
  if (resourceProfile) {
    const capture = await (await page.request.get(base + '/api/profiles/' + resourceProfile)).json();
    assert.equal(capture.device.soc, 'SM6650');
    assert.equal(capture.provenance, 'measured');
    const timeline = await (await page.request.get(base + '/api/profiles/' + resourceProfile + '/htp-timeline')).json();
    const hmx = timeline.lanes.find(lane => lane.type === 'HMX' && lane.event_count > 0);
    assert.ok(hmx?.qhas_ids.length && hmx?.trace_tracks.some(track => track.name === 'Type: HMX'));
    const event = Object.values(timeline.events).find(row => row.lane_id === hmx.id && row.flags.includes('uses_hmx'));
    assert.equal(event.assignment, 'trace_and_qhas');
    await page.goto(base + '/?' + new URLSearchParams({view:'timeline',profile:resourceProfile,event:event.event_id}));
    await page.getByText(/Capture device · .*SM6650.*Hexagon V73/).waitFor();
    await page.getByText('Optrace and QHAS agree', {exact:true}).waitFor();
    await page.getByText('Flagged resource use', {exact:true}).waitFor();
    await page.getByText('uses_hmx', {exact:true}).waitFor();
    const dma = Object.values(timeline.events).find(row => row.lane_id === hmx.id && row.flags.includes('dma_wait') && !row.flags.includes('uses_hmx'));
    assert.ok(dma);
    await page.goto(base + '/?' + new URLSearchParams({view:'timeline',profile:resourceProfile,event:dma.event_id}));
    await page.locator('.mapping-fields dd').getByText('dma_wait', {exact:true}).last().waitFor();
    await page.getByText('Optrace and QHAS agree', {exact:true}).waitFor();
    await page.screenshot({path:resolve(screenshots,'sm6650-reported-hmx-lane.png'),fullPage:true});
    checked.push({check:'Fresh SM6650 Optrace distinguishes HMX placement from DMA flags', profile:resourceProfile, hmx:event.event_id, dma:dma.event_id});
  }
  const codePredictor = catalog.models.find(model => model.name === 'Qwen3-TTS 12Hz 0.6B · Code Predictor');
  if (codePredictor) {
    const capture = catalog.profiles.find(profile => profile.model_id === codePredictor.id && profile.backend === 'CPUExecutionProvider');
    assert.equal(capture.provenance, 'measured');
    await page.goto(base + '/?' + new URLSearchParams({view:'graph',model:codePredictor.id,profile:capture.id}));
    await page.locator('.tree-layer').getByText('Layer 4', {exact:true}).waitFor();
    await page.getByRole('button', {name:'Profile this model'}).click();
    await page.getByRole('heading', {name:'Performance capture'}).waitFor();
    await page.getByText(/CPUExecutionProvider.+measured/).first().waitFor();
    checked.push({check:'Real Qwen3-TTS Code Predictor graph and ORT profile', model:codePredictor.id, profile:capture.id});
  }
  if (process.env.HTP_INSIGHT_BROWSER_ACCEPTANCE === '1') {
    // Run against a separate data directory prepared by examples.demo --tiny-only.
    async function submit(action) {
      const next = page.waitForResponse(response => response.url() === base + '/api/tools/' + action && response.request().method() === 'POST');
      await dialog.getByRole('button', {name:'Run action',exact:true}).click();
      const response = await next;
      assert.equal(response.status(), 200, await response.text());
      await dialog.waitFor({state:'hidden'});
      return response.json();
    }
    await page.goto(base + '/');
    await page.locator('.workflow-grid').getByRole('button', {name:/^Import/}).click();
    const external = resolve(data, 'external-model/tiny.onnx');
    if (existsSync(external)) {
      await dialog.getByLabel('Model file', {exact:true}).setInputFiles(external);
      await dialog.getByText('External tensors in subfolders', {exact:true}).click();
      await dialog.getByLabel('ONNX parent folder', {exact:true}).setInputFiles(dirname(external));
    } else {
      await dialog.getByLabel('Model file', {exact:true}).setInputFiles(resolve(data, 'inbox/tiny-baseline.onnx'));
    }
    await dialog.getByLabel('Display name').fill('Tiny Transformer · Browser acceptance');
    const model = await submit('import_model');
    await page.getByRole('button', {name:'Profile this model'}).click();
    async function measure() {
      await page.getByRole('button', {name:'Run ORT CPU Profile',exact:true}).click();
      await dialog.getByLabel('Input NPZ file', {exact:true}).setInputFiles(resolve(data, 'inbox/tiny-input.npz'));
      await dialog.getByText('ORT sampling settings',{exact:true}).click();
      await dialog.getByLabel('Warmup',{exact:true}).fill('5');
      await dialog.getByLabel('Timing samples',{exact:true}).fill('25');
      const capture = await submit('run_ort_profile');
      assert.equal(capture.model_id, model.artifact.id);
      assert.equal(capture.provenance, 'measured');
      assert.equal(capture.conditions.repeats, 25);
      assert.ok(capture.latency_us.p50 > 0);
      return capture;
    }
    const first = await measure();
    const second = await measure();
    assert.notEqual(first.id, second.id);
    await page.getByRole('button', {name:'Manage evidence'}).click();
    await dialog.getByLabel('Action').selectOption('compare_experiments');
    await dialog.locator('[name=baseline]').selectOption(first.id);
    await dialog.locator('[name=candidate]').selectOption(second.id);
    await dialog.getByLabel('Experiment name (optional)').fill('Browser acceptance A/A');
    await dialog.getByLabel('Hypothesis').fill('A/A: identical ONNX and inputs');
    const ab = await submit('compare_experiments');
    assert.equal(ab.latency.comparable, true);
    assert.equal(ab.numeric.passed, true);
    assert.equal(ab.name, 'Browser acceptance A/A');
    await page.getByText('Output validation', {exact:true}).waitFor();
    checked.push({check:'Web import, real ORT measurements and same-model A/A', external_tensors:existsSync(external), model:model.artifact.id, baseline:first.id, candidate:second.id, experiment:ab.id});
  }
  if (process.env.HTP_INSIGHT_BROWSER_ANDROID === '1') {
    const tiny = catalog.models.find(row => row.name === 'Tiny Transformer · Baseline · HTP W8A16');
    assert.ok(tiny);
    await page.goto(base + '/');
    await page.locator('.workflow-grid').getByRole('button', {name:/^Import/}).click();
    await dialog.getByLabel('Model file', {exact:true}).setInputFiles(resolve(data, 'android-tiny/baseline/aimet-w8a16.dlc'));
    await dialog.getByLabel('Display name').fill('Tiny Transformer · Web QAIRT Capture');
    await dialog.getByText('HTP Context compatibility', {exact:true}).click();
    await dialog.getByLabel('Source ONNX for compiled artifact').selectOption(tiny.id);
    await dialog.getByLabel('Target device (optional)').fill('SM6650');
    const bindingResponse = page.waitForResponse(response => response.url().endsWith('/tools/import_model') && response.status() === 200);
    await dialog.getByRole('button', {name:'Run action',exact:true}).click();
    const {artifact} = await (await bindingResponse).json();
    assert.equal(artifact.source_model_id, tiny.id);
    await page.getByRole('button', {name:'Open paired source ONNX'}).click();
    await page.getByRole('button', {name:'Profile this model'}).click();
    await page.getByRole('button', {name:'Run Android HTP',exact:true}).click();
    const device = page.getByRole('dialog', {name:'Android HTP capture'});
    await device.getByLabel('Paired DLC or Context').selectOption(artifact.id);
    await device.getByLabel('Raw file for hidden', {exact:true}).setInputFiles(resolve(data, 'android-tiny/inputs/hidden-0.raw'));
    await device.getByLabel('Runs', {exact:true}).fill('12');
    await device.getByLabel('Warmup', {exact:true}).fill('2');
    const capturing = page.waitForResponse(response => response.url().endsWith('/android/captures'), {timeout:90000});
    await device.getByRole('button', {name:'Start capture'}).click();
    const response = await capturing;
    assert.equal(response.status(), 200, await response.text());
    const {profile} = await response.json();
    assert.equal(profile.provenance, 'measured');
    assert.equal(profile.backend, 'QNN HTP');
    assert.equal(profile.model_id, tiny.id);
    assert.equal(profile.conditions.repeats, 10);
    await page.getByText(/QNN HTP.+measured/).first().waitFor();
    checked.push({check:'Upload DLC, bind source ONNX and run actual Android HTP from Web', artifact:artifact.id, profile:profile.id});
  }
  assert.deepEqual(errors, []);
  writeFileSync(resolve(screenshots,'browser.json'), JSON.stringify({browser:'Chromium ' + version, experiment:demo.id, checked, errors},null,2));
  console.log('Browser checks passed:', checked.map(item => item.check).join(', '));
} finally {
  await browser.close();
}
