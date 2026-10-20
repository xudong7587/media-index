function renderDiscoverFilters() {
  const node = document.getElementById("discoverFilters");
  if (!node) return;
  if (discoverState.section !== "explore") { node.innerHTML = ""; return; }
  node.innerHTML = `<div class="filter-row">
    <div class="chip-row">
      ${MEDIA_TYPES.map(([key, label]) => `<button class="chip${discoverState.mediaType === key ? " active" : ""}" data-media="${key}">${label}</button>`).join("")}
      <span class="divider"></span>
      ${REGIONS.map(([key, label]) => `<button class="chip${discoverState.region === key ? " active" : ""}" data-region="${key}">${label}</button>`).join("")}
    </div>
    <button class="chip mini" data-discover-refresh><svg class="ic ic-sm" style="vertical-align:-3px;margin-right:5px"><use href="#i-refresh"/></svg>刷新内容</button>
  </div>`;
  bindDiscoverFilters();
}
