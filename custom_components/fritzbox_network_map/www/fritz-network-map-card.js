/* FRITZ!Box Network Map Card - renderer only */
class FritzNetworkMapCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity) throw new Error("Bitte eine Netzwerk-Topologie-Entität angeben.");
    this.config = { title: "Netzwerkübersicht", colors: {}, ...config };
    this._signature = null;
  }
  set hass(hass) {
    this._hass = hass;
    if (!this.config) return;
    const state = hass.states[this.config.entity];
    const attrs = state?.attributes || {};
    const signature = JSON.stringify([attrs.topology_nodes || [], attrs.topology_edges || [], attrs.topology_groups || [], attrs.topology_display_edges || []]);
    if (signature === this._signature && this.querySelector(".fnm-wrap")) return;
    this._signature = signature;
    this.render();
  }
  getCardSize() { return 7; }
  render() {
    if (!this._hass || !this.config) return;
    const attrs = this._hass.states[this.config.entity]?.attributes || {};
    const nodes = Array.isArray(attrs.topology_nodes) ? attrs.topology_nodes : [];
    const edges = Array.isArray(attrs.topology_display_edges) ? attrs.topology_display_edges : (Array.isArray(attrs.topology_edges) ? attrs.topology_edges : []);
    const groups = Array.isArray(attrs.topology_groups) ? attrs.topology_groups : [];
    const colors = {background:"#111827",text:"#f3f4f6",line:"#64748b",router:"#2563eb",switch:"#0f766e",repeater:"#7c3aed",device:"#263445",...this.config.colors};
    const cssLength = (value, fallback) => {
      const candidate = String(value ?? fallback).trim();
      return /^(auto|\d+(?:\.\d+)?(?:px|vh|vw|dvh|dvw|%|rem|em))$/i.test(candidate) ? candidate : fallback;
    };
    const cardWidth = cssLength(this.config.width, "100%");
    const viewportHeight = cssLength(this.config.height, "55vh");
    const minViewportHeight = cssLength(this.config.min_height, "240px");
    const usesViewportWidth = /^(?:\d+(?:\.\d+)?)(?:vw|dvw)$/i.test(cardWidth);
    this.style.width = cardWidth;
    this.style.maxWidth = usesViewportWidth ? "none" : cardWidth;
    // Sections cards are constrained by their grid cell. For vw-based widths,
    // center the custom element around the viewport rather than leaving it
    // clipped/aligned to the narrow section column.
    // Break out of the centered Sections content width without using
    // left/transform positioning. Those offsets are relative to the grid
    // cell and caused horizontal displacement on tablets.
    this.style.position = "relative";
    this.style.left = "auto";
    this.style.right = "auto";
    this.style.transform = "none";
    this.style.marginLeft = usesViewportWidth ? "calc(50% - 50vw)" : "0";
    this.style.marginRight = usesViewportWidth ? "calc(50% - 50vw)" : "0";
    this.style.boxSizing = "border-box";
    const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
    const byId = new Map(nodes.map(n => [String(n.id), n]));
    const width = Math.max(900, ...nodes.map(n => Number(n.x || 0) + 268), ...groups.map(g => Number(g.x || 0) + Number(g.width || 260) + 24));
    const height = Math.max(300, ...nodes.map(n => Number(n.y || 0) + 110), ...groups.map(g => Number(g.y || 0) + Number(g.height || 112) + 24));
    const nodeW = 220, nodeH = 72;
    const groupByParent = new Map(groups.map(g => [String(g.parent_id), g]));
    const groupSvg = groups.map(g => {
      const x = Number(g.x || 0), y = Number(g.y || 0);
      const w = Number(g.width || 260), h = Number(g.height || 112);
      return `<g class="fnm-group"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="14" fill="${colors.background}" stroke="${colors.line}" stroke-width="1.5" stroke-dasharray="5 4"/><text x="${x+12}" y="${y+16}" fill="${colors.text}" opacity=".72" font-size="10">${esc(g.title || "Gerätegruppe").slice(0,60)}</text></g>`;
    }).join("");
    const groupEdgeSvg = groups.map(g => {
      const parent = byId.get(String(g.parent_id));
      if (!parent) return "";
      const x1 = Number(parent.x || 0) + nodeW;
      const y1 = Number(parent.y || 0) + nodeH / 2;
      const x2 = Number(g.x || 0);
      const y2 = Number(g.y || 0) + Number(g.height || 112) / 2;
      const midX = (x1 + x2) / 2;
      return `<path d="M ${x1} ${y1} H ${midX} V ${y2} H ${x2}" fill="none" stroke="${colors.line}" stroke-width="2.5"/>`;
    }).join("");
    const edgeSvg = edges.map(e => {
      const a = byId.get(String(e.source_id)); const b = byId.get(String(e.target_id));
      if (!a || !b) return "";
      // Render the sensor-provided edge independent of its direction on screen.
      // Geometry only: no topology inference and no additional connections.
      const ax = Number(a.x) + nodeW / 2;
      const ay = Number(a.y) + nodeH / 2;
      const bx = Number(b.x) + nodeW / 2;
      const by = Number(b.y) + nodeH / 2;
      const dx = bx - ax;
      if (dx === 0) return "";
      const direction = dx > 0 ? 1 : -1;
      const x1 = ax + direction * nodeW / 2;
      const x2 = bx - direction * nodeW / 2;
      const y1 = ay;
      const y2 = by;
      const midX = (x1 + x2) / 2;
      const dash = e.kind === "mesh" ? 'stroke-dasharray="7 5"' : "";
      // Orthogonal routing is purely visual; it draws this exact sensor edge.
      return `<path d="M ${x1} ${y1} H ${midX} V ${y2} H ${x2}" fill="none" stroke="${colors.line}" stroke-width="2.5" stroke-linejoin="round" ${dash}/>`;
    }).join("");
    const nodeSvg = nodes.map((n,i) => `<g class="fnm-node" data-id="${i}" tabindex="0" role="button"><rect x="${Number(n.x||0)}" y="${Number(n.y||0)}" width="${nodeW}" height="${nodeH}" rx="12" fill="${colors[n.kind] || colors.device}" stroke="${colors.line}" stroke-width="2"/><text x="${Number(n.x||0)+nodeW/2}" y="${Number(n.y||0)+28}" text-anchor="middle" fill="${colors.text}" font-size="13" font-weight="600">${esc(n.name || n.mac || "Gerät").slice(0,30)}</text><text x="${Number(n.x||0)+nodeW/2}" y="${Number(n.y||0)+49}" text-anchor="middle" fill="${colors.text}" opacity=".82" font-size="10">${esc([n.kind,n.switch_port].filter(Boolean).join(" · ")).slice(0,34)}</text></g>`).join("");
    this.innerHTML = `<ha-card header="${esc(this.config.title)}"><div class="fnm-wrap"><div class="fnm-toolbar">${nodes.length} Geräte · ${edges.length + groups.length} Hauptverbindungen · ${groups.length} Gruppen <button class="fnm-minus">−</button><button class="fnm-plus">+</button><button class="fnm-reset">Zurücksetzen</button></div><div class="fnm-viewport"><svg class="fnm-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="Vom Sensor gelieferte Netzwerkverbindungen">${groupSvg}${groupEdgeSvg}${edgeSvg}${nodeSvg}</svg></div><div class="fnm-detail" hidden></div><div class="fnm-note">Darstellung der vom Integration-Sensor gelieferten Gerätepositionen und Direktverbindungen. Die Karte berechnet keine Topologie.</div></div></ha-card>`;
    const style=document.createElement("style"); style.textContent=`:host{display:block;width:${cardWidth};max-width:${usesViewportWidth ? "none" : cardWidth};box-sizing:border-box;margin-left:${usesViewportWidth ? "calc(50% - 50vw)" : "0"};margin-right:${usesViewportWidth ? "calc(50% - 50vw)" : "0"}}ha-card{width:100%;height:100%;box-sizing:border-box}.fnm-wrap{background:${colors.background};color:${colors.text};padding:12px}.fnm-toolbar{display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap}.fnm-toolbar button{border:1px solid ${colors.line};background:transparent;color:${colors.text};border-radius:6px;padding:5px 10px;cursor:pointer}.fnm-viewport{width:100%;height:${viewportHeight};min-height:${minViewportHeight};overflow:auto;overscroll-behavior:contain}.fnm-svg{display:block;width:100%;height:auto;transform-origin:top left}.fnm-node{cursor:pointer}.fnm-detail{margin-top:10px;padding:12px;border:1px solid ${colors.line};border-radius:8px;line-height:1.5}.fnm-detail[hidden]{display:none}.fnm-note{font-size:11px;opacity:.7;margin-top:8px}@media(max-width:1024px){.fnm-wrap{padding:8px}}`; this.append(style);
    this._scale=this._scale||1; const svg=this.querySelector(".fnm-svg"); const apply=()=>svg.style.transform=`scale(${this._scale})`;
    this.querySelector(".fnm-plus").onclick=()=>{this._scale=Math.min(2,this._scale+.1);apply();};
    this.querySelector(".fnm-minus").onclick=()=>{this._scale=Math.max(.6,this._scale-.1);apply();};
    this.querySelector(".fnm-reset").onclick=()=>{this._scale=1;svg.style.transform="";};
    this.querySelectorAll(".fnm-node").forEach(el=>{const show=()=>{const n=nodes[Number(el.dataset.id)];const box=this.querySelector(".fnm-detail");box.hidden=false;box.innerHTML=`<strong>${esc(n.name||n.mac||n.id)}</strong><br>Typ: ${esc(n.kind||"-")}<br>IPv4: ${esc(n.ipv4||"-")}<br>MAC: ${esc(n.mac||"-")}<br>Switch: ${esc(n.switch_name||"-")}<br>Switch-Port: ${esc(n.switch_port||"-")}`;};el.addEventListener("click",show);el.addEventListener("keydown",ev=>{if(ev.key==="Enter"||ev.key===" "){ev.preventDefault();show();}});});
  }
}
if (!customElements.get("fritz-network-map-card")) customElements.define("fritz-network-map-card",FritzNetworkMapCard);
window.customCards=window.customCards||[];window.customCards.push({type:"fritz-network-map-card",name:"FRITZ!Box Network Map",description:"Renderer für sensorbasierte Netzwerkverbindungen"});
