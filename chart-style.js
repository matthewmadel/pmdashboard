/**
 * PM Dashboard — Chart Style Guide
 * Extracted from fred_dashboard.html — apply to ALL charts site-wide.
 * Requires D3 v7 to be loaded before this script.
 */

/* ═══════════════════════════════════════════════════════════════════════
   DESIGN TOKENS (mirrored from CSS :root)
════════════════════════════════════════════════════════════════════════ */
const CHART = {

  /* Colors */
  color: {
    line:        '#d4a44c',   // amber — primary series line
    lineAlt:     ['#4a90d9', '#4caf82', '#e05555', '#7c6fcd', '#3ab8a8'],  // multi-series
    area:        '#d4a44c',   // area fill (same amber, controlled by opacity)
    areaOpacity: 0.15,
    grid:        'rgba(255,255,255,0.05)',
    axis:        '#4a5068',   // text3
    axisLine:    'rgba(255,255,255,0.08)',
    recession:   'rgba(255,255,255,0.03)',
    zeroLine:    'rgba(255,255,255,0.15)',
    crosshair:   'rgba(255,255,255,0.15)',
    dot:         '#d4a44c',
    dotStroke:   '#0e1117',   // bg
    tooltipBg:   '#1f2638',   // bg4
    tooltipBorder: 'rgba(255,255,255,0.12)',
    up:          '#4caf82',
    dn:          '#e05555',
    flat:        '#8a8fa8',
  },

  /* Typography */
  font: {
    mono: "'IBM Plex Mono', monospace",
    axis: 10,      // px — axis tick labels
    tooltip: 11,   // px — tooltip body
    tooltipVal: 14, // px — tooltip value (large)
    tooltipDate: 10,
  },

  /* Layout */
  margin: { top: 20, right: 64, bottom: 36, left: 16 },
  heightMin: 220,
  heightMax: 520,
  heightDefault: 300,

  /* Line */
  strokeWidth: 1.5,
  curve: 'monotoneX',   // d3.curveMonotoneX

  /* Grid */
  yTickCount: 6,
  xTickCountShort: 8,   // ≤3Y periods
  xTickCountLong:  6,   // >3Y periods

  /* Area gradient */
  gradient: {
    id: 'pm-amber-gradient',
    start: { color: '#d4a44c', opacity: 1 },
    end:   { color: '#d4a44c', opacity: 0 },
  },

  /* Dot (hover) */
  dotRadius: 4,
  dotStrokeWidth: 2,

  /* Crosshair */
  crosshairDash: '3,3',
  crosshairWidth: 1,

  /* Zero line */
  zeroLineDash: '4,3',
  zeroLineWidth: 1,

  /* Recession bands */
  recessionFill: 'rgba(255,255,255,0.03)',

  /* Tooltip */
  tooltip: {
    padding: '8px 12px',
    borderRadius: '3px',
    boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
  },

  /* Axis */
  axis: {
    tickSize: 0,       // no tick marks, just labels
    domainRemove: true, // remove the axis domain line
  },

};

/* ═══════════════════════════════════════════════════════════════════════
   DATE FORMATTERS (axis labels)
════════════════════════════════════════════════════════════════════════ */
function fmtAxisDate(d, period) {
  const p = parseInt(period) || 99;
  if (p <= 1)  return d3.timeFormat('%b %d')(d);
  if (p <= 3)  return d3.timeFormat('%b %Y')(d);
  if (p <= 10) return d3.timeFormat('%Y')(d);
  return d3.timeFormat('%Y')(d);
}

function fmtDateLabel(str) {
  if (!str) return '';
  const d = new Date(str + 'T00:00:00');
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/* ═══════════════════════════════════════════════════════════════════════
   CHART CSS (injected into <head> once on page load)
════════════════════════════════════════════════════════════════════════ */
const CHART_CSS = `
  .pm-chart-wrap { background: var(--bg2); border: 1px solid var(--border); border-radius: var(--radius); position: relative; flex-shrink: 0; overflow: hidden; }
  .pm-chart-wrap svg { display: block; width: 100%; }
  .pm-grid-line { stroke: rgba(255,255,255,0.05); stroke-width: 1; }
  .pm-axis-label { font-family: 'IBM Plex Mono'; fill: #4a5068; font-size: 10px; }
  .pm-axis-line { stroke: rgba(255,255,255,0.08); stroke-width: 1; }
  .pm-recession { fill: rgba(255,255,255,0.03); }
  .pm-chart-line { fill: none; stroke-width: 1.5; stroke-linejoin: round; stroke-linecap: round; }
  .pm-area { opacity: 0.15; }
  .pm-zero-line { stroke: rgba(255,255,255,0.15); stroke-width: 1; stroke-dasharray: 4 3; }
  .pm-crosshair { stroke: rgba(255,255,255,0.15); stroke-width: 1; stroke-dasharray: 3 3; pointer-events: none; }
  .pm-hover-dot { fill: #d4a44c; stroke: #0e1117; stroke-width: 2; }
  .pm-tooltip {
    position: absolute; pointer-events: none; opacity: 0; transition: opacity .1s;
    background: #1f2638; border: 1px solid rgba(255,255,255,0.12);
    padding: 8px 12px; border-radius: 3px; white-space: nowrap;
    font-family: 'IBM Plex Mono', monospace; font-size: 11px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.5); z-index: 10;
  }
  .pm-tt-date { color: #4a5068; font-size: 10px; margin-bottom: 4px; }
  .pm-tt-val  { font-size: 14px; font-weight: 500; margin-bottom: 2px; }
  .pm-tt-chg  { font-size: 10px; }
  .pm-tt-up   { color: #4caf82; }
  .pm-tt-dn   { color: #e05555; }
  .pm-tt-flat { color: #8a8fa8; }
  .pm-legend  { display: flex; gap: 14px; padding: 8px 16px 10px; flex-wrap: wrap; }
  .pm-legend-item { display: flex; align-items: center; gap: 5px; font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: #8a8fa8; }
  .pm-legend-swatch { width: 20px; height: 2px; border-radius: 1px; flex-shrink: 0; }
  .pm-no-data { display: flex; align-items: center; justify-content: center; height: 100%; font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: #4a5068; letter-spacing: 0.06em; text-transform: uppercase; }
`;

function injectChartCSS() {
  if (document.getElementById('pm-chart-css')) return;
  const s = document.createElement('style');
  s.id = 'pm-chart-css';
  s.textContent = CHART_CSS;
  document.head.appendChild(s);
}

/* ═══════════════════════════════════════════════════════════════════════
   CORE: drawLineChart(container, data, options)
   
   container : DOM element (the .pm-chart-wrap div)
   data      : Array of { date: 'YYYY-MM-DD', value: Number }
                OR Array of series: [{ label, color, data: [...] }]
   options   : {
     period      : '1Y' | '3Y' | '5Y' etc (for axis formatting)
     height      : Number (optional, px)
     showArea    : Boolean (default true for single series)
     showRecessions : Array of { start, end } date strings
     yFormat     : function(v) → string  (y-axis tick formatter)
     tooltipFormat: function(v) → string (tooltip value formatter)
     multiSeries : Boolean (if data is array of series objects)
     showLegend  : Boolean
   }
════════════════════════════════════════════════════════════════════════ */
function drawLineChart(container, data, options = {}) {
  injectChartCSS();
  if (!container) return;

  // Clear previous
  container.innerHTML = '';

  const isMulti = options.multiSeries && Array.isArray(data) && data[0]?.data;
  const series  = isMulti ? data : [{ label: '', color: CHART.color.line, data }];

  // Validate
  const allPoints = series.flatMap(s => s.data || []);
  if (!allPoints.length) {
    container.innerHTML = '<div class="pm-no-data" style="height:200px">No data available</div>';
    return;
  }

  const period = options.period || '5Y';
  const W = container.clientWidth || 800;
  const H = options.height || Math.max(CHART.heightMin, Math.min(CHART.heightMax, CHART.heightDefault));
  const m = CHART.margin;
  const iw = W - m.left - m.right;
  const ih = H - m.top  - m.bottom;

  // Tooltip element
  const tt = document.createElement('div');
  tt.className = 'pm-tooltip';
  tt.innerHTML = `<div class="pm-tt-date"></div><div class="pm-tt-val"></div><div class="pm-tt-chg"></div>`;
  container.appendChild(tt);

  // SVG
  const svg = d3.select(container).append('svg')
    .attr('width', W).attr('height', H);

  const g = svg.append('g').attr('transform', `translate(${m.left},${m.top})`);

  // Defs — gradient
  const defs = svg.append('defs');
  const grad = defs.append('linearGradient')
    .attr('id', CHART.gradient.id)
    .attr('x1', 0).attr('x2', 0).attr('y1', 0).attr('y2', 1);
  grad.append('stop').attr('offset', '0%').attr('stop-color', CHART.gradient.start.color).attr('stop-opacity', CHART.gradient.start.opacity);
  grad.append('stop').attr('offset', '100%').attr('stop-color', CHART.gradient.end.color).attr('stop-opacity', CHART.gradient.end.opacity);

  // Parse dates
  const parseDate = d3.timeParse('%Y-%m-%d');
  const parsedSeries = series.map(s => ({
    ...s,
    parsed: (s.data || []).map(d => ({ date: parseDate(d.date), value: d.value })).filter(d => d.date && !isNaN(d.value))
  }));

  // Scales
  const allDates  = parsedSeries.flatMap(s => s.parsed.map(d => d.date));
  const allValues = parsedSeries.flatMap(s => s.parsed.map(d => d.value));
  const xScale = d3.scaleTime().domain(d3.extent(allDates)).range([0, iw]);
  const [vmin, vmax] = d3.extent(allValues);
  const pad    = (vmax - vmin) * 0.07 || 0.5;
  const yScale = d3.scaleLinear().domain([vmin - pad, vmax + pad]).range([ih, 0]).nice();

  // Recession bands
  if (options.showRecessions && options.showRecessions.length) {
    for (const r of options.showRecessions) {
      const rx0 = xScale(parseDate(r.start) || allDates[0]);
      const rx1 = xScale(parseDate(r.end)   || allDates[allDates.length-1]);
      if (rx1 > rx0) {
        g.append('rect').attr('class', 'pm-recession')
          .attr('x', Math.max(0, rx0)).attr('y', 0)
          .attr('width', Math.min(rx1 - rx0, iw - Math.max(0, rx0))).attr('height', ih);
      }
    }
  }

  // Zero line
  if (vmin < 0 && vmax > 0) {
    g.append('line').attr('class', 'pm-zero-line')
      .attr('x1', 0).attr('x2', iw)
      .attr('y1', yScale(0)).attr('y2', yScale(0));
  }

  // Y grid lines
  const yTicks = yScale.ticks(CHART.yTickCount);
  g.selectAll('.pm-grid-line').data(yTicks).enter().append('line')
    .attr('class', 'pm-grid-line')
    .attr('x1', 0).attr('x2', iw)
    .attr('y1', d => yScale(d)).attr('y2', d => yScale(d));

  // X axis
  const isShort = parseInt(period) <= 3;
  const xAxis = d3.axisBottom(xScale)
    .ticks(isShort ? CHART.xTickCountShort : CHART.xTickCountLong)
    .tickFormat(d => fmtAxisDate(d, period))
    .tickSize(0);
  g.append('g').attr('transform', `translate(0,${ih + 8})`)
    .call(xAxis)
    .call(a => a.select('.domain').remove())
    .selectAll('text')
    .attr('fill', CHART.color.axis)
    .attr('font-family', CHART.font.mono)
    .attr('font-size', CHART.font.axis);

  // Y axis (right)
  const yFmt = options.yFormat || (v => d3.format(',.2~f')(v));
  const yAxis = d3.axisRight(yScale)
    .ticks(CHART.yTickCount)
    .tickFormat(yFmt)
    .tickSize(0);
  g.append('g').attr('transform', `translate(${iw + 8},0)`)
    .call(yAxis)
    .call(a => a.select('.domain').remove())
    .selectAll('text')
    .attr('fill', CHART.color.axis)
    .attr('font-family', CHART.font.mono)
    .attr('font-size', CHART.font.axis);

  // Draw each series
  const curveMap = { monotoneX: d3.curveMonotoneX, linear: d3.curveLinear, step: d3.curveStep };
  const curve = curveMap[CHART.curve] || d3.curveMonotoneX;

  parsedSeries.forEach((s, si) => {
    const color = s.color || (si === 0 ? CHART.color.line : CHART.color.lineAlt[si - 1]);

    // Area (single series or explicitly requested)
    const showArea = options.showArea !== false && (si === 0 || options.showArea === true);
    if (showArea) {
      const area = d3.area()
        .x(d => xScale(d.date)).y0(ih).y1(d => yScale(d.value))
        .defined(d => !isNaN(d.value)).curve(curve);
      g.append('path').datum(s.parsed)
        .attr('d', area)
        .attr('fill', si === 0 ? `url(#${CHART.gradient.id})` : color)
        .attr('opacity', CHART.color.areaOpacity);
    }

    // Line
    const line = d3.line()
      .x(d => xScale(d.date)).y(d => yScale(d.value))
      .defined(d => !isNaN(d.value)).curve(curve);
    g.append('path').datum(s.parsed)
      .attr('d', line)
      .attr('class', 'pm-chart-line')
      .attr('stroke', color);
  });

  // ── Hover interaction (primary series only for tooltip) ──────────────
  const primaryParsed = parsedSeries[0].parsed;
  const primaryData   = series[0].data || [];
  const primaryColor  = parsedSeries[0].color || CHART.color.line;

  const crossV = g.append('line').attr('class', 'pm-crosshair').attr('y1', 0).attr('y2', ih).style('opacity', 0);
  const crossH = g.append('line').attr('class', 'pm-crosshair').attr('x1', 0).attr('x2', iw).style('opacity', 0);
  const dot    = g.append('circle').attr('class', 'pm-hover-dot').attr('r', CHART.dotRadius).style('opacity', 0).attr('stroke', CHART.color.dotStroke);

  const bisect = d3.bisector(d => d.date).left;
  const ttDate = tt.querySelector('.pm-tt-date');
  const ttVal  = tt.querySelector('.pm-tt-val');
  const ttChg  = tt.querySelector('.pm-tt-chg');
  const valFmt = options.tooltipFormat || yFmt;

  svg.append('rect')
    .attr('width', iw).attr('height', ih)
    .attr('transform', `translate(${m.left},${m.top})`)
    .attr('fill', 'transparent')
    .on('mousemove', function(event) {
      const [mx] = d3.pointer(event, this);
      const xDate = xScale.invert(mx);
      const i = bisect(primaryParsed, xDate);
      const d = primaryParsed[Math.min(i, primaryParsed.length - 1)] || primaryParsed[i - 1];
      if (!d) return;
      const px = xScale(d.date), py = yScale(d.value);
      crossV.attr('x1', px).attr('x2', px).style('opacity', 1);
      crossH.attr('y1', py).attr('y2', py).style('opacity', 1);
      dot.attr('cx', px).attr('cy', py).style('opacity', 1).attr('fill', primaryColor);

      const prev = i > 0 ? primaryParsed[i - 1] : null;
      const dc   = prev ? d.value - prev.value : null;
      const raw  = primaryData[Math.min(i, primaryData.length - 1)];

      ttDate.textContent = raw ? fmtDateLabel(raw.date) : '';
      ttVal.textContent  = valFmt(d.value);
      ttVal.style.color  = primaryColor;
      if (dc != null) {
        const sign = dc >= 0 ? '▲ ' : '▼ ';
        ttChg.textContent = sign + Math.abs(dc).toFixed(3);
        ttChg.className   = 'pm-tt-chg ' + (dc >= 0 ? 'pm-tt-up' : 'pm-tt-dn');
      } else {
        ttChg.textContent = '';
      }

      // Position tooltip — flip if too close to right edge
      const rx = m.left + px + 14;
      const ry = m.top  + py - 24;
      tt.style.left    = (rx + 170 > W ? rx - 185 : rx) + 'px';
      tt.style.top     = Math.max(0, ry) + 'px';
      tt.style.opacity = 1;
    })
    .on('mouseleave', () => {
      crossV.style('opacity', 0);
      crossH.style('opacity', 0);
      dot.style('opacity', 0);
      tt.style.opacity = 0;
    });

  // ── Legend (multi-series) ────────────────────────────────────────────
  if (options.showLegend && isMulti) {
    const legend = document.createElement('div');
    legend.className = 'pm-legend';
    parsedSeries.forEach((s, si) => {
      const color = s.color || (si === 0 ? CHART.color.line : CHART.color.lineAlt[si - 1]);
      const item = document.createElement('div');
      item.className = 'pm-legend-item';
      item.innerHTML = `<div class="pm-legend-swatch" style="background:${color}"></div><span>${s.label}</span>`;
      legend.appendChild(item);
    });
    container.appendChild(legend);
  }
}

/* ═══════════════════════════════════════════════════════════════════════
   CONVENIENCE: drawBarChart(container, data, options)
   For performance bar charts (YTD returns etc.)
════════════════════════════════════════════════════════════════════════ */
function drawBarChart(container, data, options = {}) {
  injectChartCSS();
  if (!container || !data.length) return;

  container.innerHTML = '';
  const W  = container.clientWidth || 800;
  const H  = options.height || 200;
  const m  = { top: 14, right: 64, bottom: 48, left: 16 };
  const iw = W - m.left - m.right;
  const ih = H - m.top  - m.bottom;

  const tt = document.createElement('div');
  tt.className = 'pm-tooltip';
  tt.innerHTML = `<div class="pm-tt-date"></div><div class="pm-tt-val"></div>`;
  container.appendChild(tt);

  const svg = d3.select(container).append('svg').attr('width', W).attr('height', H);
  const g   = svg.append('g').attr('transform', `translate(${m.left},${m.top})`);

  const xScale = d3.scaleBand().domain(data.map(d => d.label)).range([0, iw]).padding(0.3);
  const vals   = data.map(d => d.value);
  const vmin   = Math.min(0, d3.min(vals));
  const vmax   = d3.max(vals);
  const pad    = (vmax - vmin) * 0.08 || 0.5;
  const yScale = d3.scaleLinear().domain([vmin - pad, vmax + pad]).range([ih, 0]).nice();

  // Grid
  yScale.ticks(5).forEach(t => {
    g.append('line').attr('class', 'pm-grid-line')
      .attr('x1', 0).attr('x2', iw).attr('y1', yScale(t)).attr('y2', yScale(t));
  });

  // Zero line
  g.append('line').attr('class', 'pm-zero-line')
    .attr('x1', 0).attr('x2', iw).attr('y1', yScale(0)).attr('y2', yScale(0));

  // Bars
  const valFmt = options.format || (v => (v >= 0 ? '+' : '') + v.toFixed(2) + '%');
  data.forEach(d => {
    const color = d.value >= 0 ? CHART.color.up : CHART.color.dn;
    const barH  = Math.abs(yScale(d.value) - yScale(0));
    const barY  = d.value >= 0 ? yScale(d.value) : yScale(0);
    const bar   = g.append('rect')
      .attr('x', xScale(d.label)).attr('y', barY)
      .attr('width', xScale.bandwidth()).attr('height', Math.max(1, barH))
      .attr('fill', color).attr('opacity', 0.85)
      .attr('rx', 1).style('cursor', 'pointer');

    bar.on('mousemove', function(event) {
      const [mx, my] = d3.pointer(event, container);
      tt.querySelector('.pm-tt-date').textContent = d.label;
      const valEl = tt.querySelector('.pm-tt-val');
      valEl.textContent = valFmt(d.value);
      valEl.style.color = color;
      tt.style.left = (mx + 12) + 'px';
      tt.style.top  = (my - 40) + 'px';
      tt.style.opacity = 1;
    }).on('mouseleave', () => { tt.style.opacity = 0; });
  });

  // X axis labels
  g.append('g').attr('transform', `translate(0,${ih + 8})`)
    .call(d3.axisBottom(xScale).tickSize(0))
    .call(a => a.select('.domain').remove())
    .selectAll('text')
    .attr('fill', CHART.color.axis)
    .attr('font-family', CHART.font.mono)
    .attr('font-size', 10)
    .attr('text-anchor', 'middle');

  // Y axis
  g.append('g').attr('transform', `translate(${iw + 8},0)`)
    .call(d3.axisRight(yScale).ticks(5).tickFormat(valFmt).tickSize(0))
    .call(a => a.select('.domain').remove())
    .selectAll('text')
    .attr('fill', CHART.color.axis)
    .attr('font-family', CHART.font.mono)
    .attr('font-size', 10);
}

/* ═══════════════════════════════════════════════════════════════════════
   CONVENIENCE: drawHeatmap(container, matrix, rowLabels, colLabels)
   For correlation matrix
════════════════════════════════════════════════════════════════════════ */
function drawHeatmap(container, matrix, rowLabels, colLabels, options = {}) {
  injectChartCSS();
  if (!container) return;
  container.innerHTML = '';

  const n   = rowLabels.length;
  const labelW = 110;
  const cellSize = options.cellSize || Math.min(52, Math.floor((container.clientWidth - labelW - 20) / n));
  const W   = labelW + cellSize * n + 20;
  const H   = labelW + cellSize * n + 20;

  const tt = document.createElement('div');
  tt.className = 'pm-tooltip';
  tt.innerHTML = `<div class="pm-tt-date"></div><div class="pm-tt-val"></div>`;
  container.appendChild(tt);

  const svg = d3.select(container).append('svg').attr('width', W).attr('height', H);
  const g   = svg.append('g').attr('transform', `translate(${labelW},${labelW})`);

  const colorScale = d3.scaleLinear()
    .domain([-1, 0, 1])
    .range(['#e05555', '#1a2030', '#4caf82']);

  // Cells
  matrix.forEach((row, ri) => {
    row.forEach((val, ci) => {
      const cell = g.append('rect')
        .attr('x', ci * cellSize).attr('y', ri * cellSize)
        .attr('width', cellSize - 2).attr('height', cellSize - 2)
        .attr('rx', 2).attr('fill', colorScale(val))
        .style('cursor', 'pointer');

      g.append('text')
        .attr('x', ci * cellSize + cellSize / 2)
        .attr('y', ri * cellSize + cellSize / 2 + 4)
        .attr('text-anchor', 'middle')
        .attr('font-family', CHART.font.mono)
        .attr('font-size', 9)
        .attr('fill', Math.abs(val) > 0.4 ? '#e8e2d9' : '#8a8fa8')
        .text(val.toFixed(2));

      cell.on('mousemove', function(event) {
        const [mx, my] = d3.pointer(event, container);
        tt.querySelector('.pm-tt-date').textContent = `${rowLabels[ri]} × ${colLabels[ci]}`;
        const valEl = tt.querySelector('.pm-tt-val');
        valEl.textContent = val.toFixed(3);
        valEl.style.color = colorScale(val);
        tt.style.left = (mx + 12) + 'px';
        tt.style.top  = (my - 40) + 'px';
        tt.style.opacity = 1;
      }).on('mouseleave', () => { tt.style.opacity = 0; });
    });
  });

  // Row labels (left)
  rowLabels.forEach((label, ri) => {
    svg.append('text')
      .attr('x', labelW - 8)
      .attr('y', labelW + ri * cellSize + cellSize / 2 + 4)
      .attr('text-anchor', 'end')
      .attr('font-family', CHART.font.mono)
      .attr('font-size', 9)
      .attr('fill', CHART.color.axis)
      .text(label);
  });

  // Column labels (top, rotated)
  colLabels.forEach((label, ci) => {
    svg.append('text')
      .attr('transform', `translate(${labelW + ci * cellSize + cellSize / 2},${labelW - 8}) rotate(-45)`)
      .attr('text-anchor', 'start')
      .attr('font-family', CHART.font.mono)
      .attr('font-size', 9)
      .attr('fill', CHART.color.axis)
      .text(label);
  });
}
