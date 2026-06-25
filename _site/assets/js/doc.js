(() => {
  const panels = Array.from(document.querySelectorAll("section.panel[id]"));
  const tabButtons = Array.from(document.querySelectorAll("nav.tabs button[data-tab]"));
  const generatedPages = Array.from(document.querySelectorAll(".doc-section-page[id]"));
  const prevButton = document.querySelector("[data-doc-prev]");
  const nextButton = document.querySelector("[data-doc-next]");
  const status = document.querySelector("[data-doc-status]");
  let sectionSearchInput = null;
  let sectionSearchCount = null;
  let sectionSearchClear = null;
  let sectionSearchResults = null;
  let sectionSearchQuery = "";
  let activeItem = null;

  const items = panels.length
    ? panels.map((panel) => ({
        id: panel.id,
        title: (tabButtons.find((button) => button.dataset.tab === panel.id)?.textContent || panel.querySelector("h2,h3,h1")?.textContent || panel.id).trim(),
        element: panel,
      }))
    : generatedPages.map((page) => ({
        id: page.id,
        title: (page.dataset.sectionTitle || page.querySelector("h2,h3,h1")?.textContent || page.id).trim(),
        element: page,
      }));

  if (!items.length) {
    return;
  }

  const itemIds = new Set(items.map((item) => item.id));
  let activeIndex = 0;

  function notifyParent(item) {
    try {
      window.parent.postMessage({
        type: "doc-section-change",
        sectionId: item.id,
        section: item.title,
      }, "*");
    } catch (_error) {
      // File URLs may restrict parent messaging in some browsers; the page still works without it.
    }
  }

  function createSectionSearch() {
    const bar = document.createElement("div");
    bar.className = "section-search-bar";

    const label = document.createElement("label");
    sectionSearchInput = document.createElement("input");
    sectionSearchInput.type = "search";
    sectionSearchInput.autocomplete = "off";
    sectionSearchInput.className = "section-search-input";
    sectionSearchInput.placeholder = "Search current section...";
    label.appendChild(sectionSearchInput);

    sectionSearchCount = document.createElement("span");
    sectionSearchCount.className = "section-search-count";
    sectionSearchCount.textContent = "Current section";

    sectionSearchClear = document.createElement("button");
    sectionSearchClear.type = "button";
    sectionSearchClear.className = "section-search-clear";
    sectionSearchClear.textContent = "Clear";

    sectionSearchResults = document.createElement("div");
    sectionSearchResults.className = "section-search-results";

    bar.append(label, sectionSearchCount, sectionSearchClear, sectionSearchResults);

    const tabs = document.querySelector("nav.tabs");
    const pager = document.querySelector(".doc-pager");
    const anchor = tabs || pager || document.querySelector(".document > *");
    if (anchor && anchor.parentNode) {
      anchor.insertAdjacentElement("afterend", bar);
    } else {
      document.querySelector(".document")?.prepend(bar);
    }

    sectionSearchInput.addEventListener("input", () => {
      sectionSearchQuery = sectionSearchInput.value || "";
      runSectionSearch();
    });
    sectionSearchClear.addEventListener("click", () => {
      sectionSearchInput.value = "";
      sectionSearchQuery = "";
      runSectionSearch();
      sectionSearchInput.focus();
    });
  }

  function clearHighlights(root = document) {
    const marks = Array.from(root.querySelectorAll("mark.section-search-hit"));
    marks.forEach((mark) => {
      mark.replaceWith(document.createTextNode(mark.textContent || ""));
    });
    root.normalize();
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function snippetForMark(mark, query) {
    const text = (mark.parentElement?.textContent || mark.textContent || "").replace(/\s+/g, " ").trim();
    const index = text.toLowerCase().indexOf(query.toLowerCase());
    const start = index >= 0 ? Math.max(0, index - 44) : 0;
    const end = index >= 0 ? Math.min(text.length, index + query.length + 66) : Math.min(text.length, 120);
    let snippet = `${start > 0 ? "... " : ""}${text.slice(start, end)}${end < text.length ? " ..." : ""}`;
    const escaped = escapeHtml(query).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return escapeHtml(snippet).replace(new RegExp(escaped, "ig"), (match) => `<strong>${match}</strong>`);
  }

  function searchableTextNodes(root) {
    const nodes = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent || !node.nodeValue.trim()) {
          return NodeFilter.FILTER_REJECT;
        }
        if (parent.closest("script, style, textarea, input, button, mark")) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    while (walker.nextNode()) {
      nodes.push(walker.currentNode);
    }
    return nodes;
  }

  function highlightNode(textNode, query) {
    const text = textNode.nodeValue;
    const lower = text.toLowerCase();
    const needle = query.toLowerCase();
    let index = lower.indexOf(needle);
    if (index === -1) {
      return 0;
    }
    let count = 0;
    const frag = document.createDocumentFragment();
    let cursor = 0;
    while (index !== -1) {
      if (index > cursor) {
        frag.appendChild(document.createTextNode(text.slice(cursor, index)));
      }
      const mark = document.createElement("mark");
      mark.className = "section-search-hit";
      mark.textContent = text.slice(index, index + query.length);
      frag.appendChild(mark);
      count += 1;
      cursor = index + query.length;
      index = lower.indexOf(needle, cursor);
    }
    if (cursor < text.length) {
      frag.appendChild(document.createTextNode(text.slice(cursor)));
    }
    textNode.replaceWith(frag);
    return count;
  }

  function runSectionSearch() {
    items.forEach((item) => clearHighlights(item.element));
    if (sectionSearchResults) {
      sectionSearchResults.textContent = "";
      sectionSearchResults.classList.remove("show");
    }
    const query = sectionSearchQuery.trim();
    if (!sectionSearchCount) {
      return;
    }
    if (!query || query.length < 2 || !activeItem) {
      sectionSearchCount.textContent = activeItem ? "Current section" : "";
      return;
    }
    let count = 0;
    searchableTextNodes(activeItem.element).forEach((node) => {
      count += highlightNode(node, query);
    });
    sectionSearchCount.textContent = count === 1 ? "1 match" : `${count} matches`;
    const marks = Array.from(activeItem.element.querySelectorAll("mark.section-search-hit"));

    function goToMatch(index, resultButton = null) {
      const target = marks[index];
      if (!target) {
        return;
      }
      marks.forEach((mark) => mark.classList.remove("is-current"));
      target.classList.add("is-current");
      target.setAttribute("tabindex", "-1");
      if (sectionSearchResults) {
        sectionSearchResults.querySelectorAll(".section-result").forEach((item) => item.classList.remove("is-active"));
      }
      if (resultButton) {
        resultButton.classList.add("is-active");
      }
      requestAnimationFrame(() => {
        target.scrollIntoView({ block: "center", inline: "nearest", behavior: "auto" });
        target.focus({ preventScroll: true });
      });
    }

    marks.forEach((mark, index) => {
      mark.id = `section-search-hit-${index + 1}`;
      if (!sectionSearchResults) {
        return;
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = "section-result";
      button.innerHTML = snippetForMark(mark, query);
      button.addEventListener("click", () => {
        goToMatch(index, button);
      });
      sectionSearchResults.appendChild(button);
    });
    if (sectionSearchResults && marks.length) {
      sectionSearchResults.classList.add("show");
    }
    const firstResult = sectionSearchResults?.querySelector(".section-result");
    if (marks[0]) {
      goToMatch(0, firstResult);
    }
  }

  function activate(itemId, updateHash = false, scrollToTop = true) {
    if (!itemIds.has(itemId)) {
      itemId = items[0].id;
    }
    activeIndex = items.findIndex((item) => item.id === itemId);
    activeItem = items[activeIndex];

    items.forEach((item) => item.element.classList.toggle("active", item.id === itemId));
    tabButtons.forEach((button) => {
      const active = button.dataset.tab === itemId;
      button.classList.toggle("active", active);
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });

    if (prevButton) {
      prevButton.disabled = activeIndex <= 0;
    }
    if (nextButton) {
      nextButton.disabled = activeIndex >= items.length - 1;
    }
    if (status) {
      status.textContent = `${activeIndex + 1} of ${items.length}: ${activeItem.title}`;
    }

    if (updateHash && window.location.hash !== `#${itemId}`) {
      history.replaceState(null, "", `#${itemId}`);
    }

    notifyParent(activeItem);
    runSectionSearch();
    if (scrollToTop) {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  tabButtons.forEach((button) => {
    button.type = "button";
    button.setAttribute("role", "tab");
    button.addEventListener("click", () => activate(button.dataset.tab, true));
  });

  if (prevButton) {
    prevButton.addEventListener("click", () => {
      if (activeIndex > 0) {
        activate(items[activeIndex - 1].id, true);
      }
    });
  }
  if (nextButton) {
    nextButton.addEventListener("click", () => {
      if (activeIndex < items.length - 1) {
        activate(items[activeIndex + 1].id, true);
      }
    });
  }

  createSectionSearch();
  const initialQuery = new URLSearchParams(window.location.search).get("q") || "";
  if (initialQuery && sectionSearchInput) {
    sectionSearchInput.value = initialQuery;
    sectionSearchQuery = initialQuery;
  }

  const requested = decodeURIComponent(window.location.hash.replace(/^#/, ""));
  const activePanel = tabButtons.find((button) => button.classList.contains("active"));
  const initial = itemIds.has(requested)
    ? requested
    : (activePanel ? activePanel.dataset.tab : items[0].id);

  activate(initial, false);

  window.addEventListener("hashchange", () => {
    const next = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    if (itemIds.has(next)) {
      activate(next, false);
    }
  });
})();
