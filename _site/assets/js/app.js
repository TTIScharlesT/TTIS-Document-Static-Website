(() => {
  const manifest = window.SITE_MANIFEST || { tabs: [] };
  const tabList = document.getElementById("tab-list");
  const pageList = document.getElementById("page-list");
  const sidebarHeading = document.getElementById("sidebar-heading");
  const sidebarCurrent = document.getElementById("sidebar-current");
  const frame = document.getElementById("reader-frame");
  const searchInput = document.getElementById("site-search");

  const tabs = manifest.tabs || [];
  let searchQuery = "";
  const collapsedPages = new Set();
  const collapsedSections = new Set();

  function allPages() {
    return tabs.flatMap((tab) => (tab.pages || []).map((page) => ({ ...page, tabName: tab.name, tabDir: tab.dir })));
  }

  function findTab(dir) {
    return tabs.find((tab) => tab.dir === dir) || tabs[0];
  }

  function findPage(tab, slug) {
    if (!tab || !tab.pages || !tab.pages.length) {
      return null;
    }
    return tab.pages.find((page) => page.slug === slug) || tab.pages[0];
  }

  function parseRoute() {
    const raw = window.location.hash.replace(/^#\/?/, "");
    const [path, queryText] = raw.split("?");
    const parts = path.split("/").filter(Boolean);
    const params = new URLSearchParams(queryText || "");
    return {
      tabDir: parts[0],
      slug: parts[1],
      anchor: params.get("anchor") || "",
      q: params.get("q") || "",
    };
  }

  function setRoute(tab, page, anchor = "", query = "") {
    if (!tab || !page) {
      return;
    }
    let next = `#/${tab.dir}/${page.slug}`;
    const params = new URLSearchParams();
    if (anchor) {
      params.set("anchor", anchor);
    }
    if (query) {
      params.set("q", query);
    }
    const qs = params.toString();
    if (qs) {
      next += `?${qs}`;
    }
    if (window.location.hash !== next) {
      window.location.hash = next;
    } else {
      render();
    }
  }

  function pageKey(tab, page) {
    return `${tab.dir}/${page.slug}`;
  }

  function sectionDepth(section) {
    const match = (section.title || "").match(/^(\d+(?:\.\d+)*)\b/);
    if (!match) {
      return 1;
    }
    return match[1].split(".").length;
  }

  function rootSectionId(sections, sectionId) {
    if (!sections || !sections.length) {
      return "";
    }
    const activeIndex = Math.max(0, sections.findIndex((section) => section.id === sectionId));
    for (let i = activeIndex; i >= 0; i -= 1) {
      if (sectionDepth(sections[i]) === 1) {
        return sections[i].id;
      }
    }
    return sections[0].id;
  }

  function sectionVisible(sections, section, index, activeRootId) {
    if (sectionDepth(section) === 1) {
      return true;
    }
    const rootId = rootSectionId(sections, section.id);
    return rootId === activeRootId && !collapsedSections.has(rootId);
  }

  function renderTabs(activeTab) {
    tabList.textContent = "";
    tabs.forEach((tab) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `tab-button${tab.dir === activeTab.dir ? " is-active" : ""}`;
      button.textContent = tab.name;
      button.addEventListener("click", () => setRoute(tab, tab.pages[0]));
      tabList.appendChild(button);
    });
  }

  function searchMatches() {
    const raw = searchQuery.trim();
    const q = raw.toLowerCase();
    if (!q) {
      return [];
    }
    const results = [];
    allPages().forEach((page) => {
      const titleMatch = page.title.toLowerCase().includes(q) || page.tabName.toLowerCase().includes(q) || page.slug.toLowerCase().includes(q);
      const sections = page.sections && page.sections.length ? page.sections : [{ id: "", title: page.title, text: "" }];
      sections.forEach((section) => {
        const haystack = `${page.title} ${section.title || ""} ${section.text || ""}`.toLowerCase();
        if (!titleMatch && !haystack.includes(q)) {
          return;
        }
        results.push({
          ...page,
          tabName: page.tabName,
          tabDir: page.tabDir,
          sectionId: section.id || "",
          sectionTitle: section.title || page.title,
          snippet: makeSnippet(section.text || page.title, raw),
        });
      });
    });
    return results.slice(0, 80);
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function makeSnippet(text, query) {
    const source = String(text || "").replace(/\s+/g, " ").trim();
    if (!source) {
      return "";
    }
    const index = source.toLowerCase().indexOf(query.toLowerCase());
    const start = index >= 0 ? Math.max(0, index - 58) : 0;
    const end = index >= 0 ? Math.min(source.length, index + query.length + 82) : Math.min(source.length, 150);
    let snippet = `${start > 0 ? "... " : ""}${source.slice(start, end)}${end < source.length ? " ..." : ""}`;
    if (query) {
      const escaped = escapeHtml(query).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      snippet = escapeHtml(snippet).replace(new RegExp(escaped, "ig"), (match) => `<strong>${match}</strong>`);
    }
    return snippet;
  }

  function renderPages(activeTab, activePage, activeSection = "") {
    pageList.textContent = "";
    const matches = searchMatches();
    const showingSearch = Boolean(searchQuery.trim());
    const pageSet = showingSearch ? matches : ((activeTab && activeTab.pages) || []).map((page) => ({ ...page, tabName: activeTab.name, tabDir: activeTab.dir }));

    sidebarHeading.textContent = showingSearch ? `Search results (${matches.length})` : (activeTab ? activeTab.name : "Documents");

    if (!pageSet.length) {
      const empty = document.createElement("div");
      empty.className = "page-link";
      empty.textContent = showingSearch ? "No matching documents" : "No documents";
      pageList.appendChild(empty);
      return;
    }
    pageSet.forEach((page) => {
      const targetTab = showingSearch ? findTab(page.tabDir) : activeTab;
      const targetPage = showingSearch ? findPage(targetTab, page.slug) : page;
      const isActivePage = targetTab.dir === activeTab.dir && targetPage.slug === activePage.slug;
      const button = document.createElement("button");
      button.type = "button";
      button.className = `page-link${isActivePage ? " is-active" : ""}`;
      if (showingSearch) {
        const label = document.createElement("span");
        label.className = "page-tab";
        label.textContent = page.tabName;
        button.appendChild(label);
      }
      button.append(document.createTextNode(page.title));
      if (showingSearch) {
        const section = document.createElement("span");
        section.className = "search-section";
        section.textContent = page.sectionTitle || page.title;
        const snippet = document.createElement("span");
        snippet.className = "search-snippet";
        snippet.innerHTML = page.snippet || "Title match";
        button.append(section, snippet);
      }
      button.addEventListener("click", () => {
        if (isActivePage && !showingSearch && targetPage.sections && targetPage.sections.length > 1) {
          const key = pageKey(targetTab, targetPage);
          if (collapsedPages.has(key)) {
            collapsedPages.delete(key);
          } else {
            collapsedPages.add(key);
          }
          renderPages(activeTab, activePage, activeSection);
          return;
        }
        setRoute(targetTab, targetPage, showingSearch ? page.sectionId : "", showingSearch ? searchQuery.trim() : "");
      });
      pageList.appendChild(button);

      const activePageKey = pageKey(targetTab, targetPage);
      if (!showingSearch && isActivePage && targetPage.sections && targetPage.sections.length > 1 && !collapsedPages.has(activePageKey)) {
        const sectionList = document.createElement("div");
        sectionList.className = "section-list";
        const effectiveSection = activeSection || targetPage.sections[0].id;
        const activeRootId = rootSectionId(targetPage.sections, effectiveSection);
        targetPage.sections.forEach((section, index) => {
          if (!sectionVisible(targetPage.sections, section, index, activeRootId)) {
            return;
          }
          const depth = sectionDepth(section);
          const sectionButton = document.createElement("button");
          sectionButton.type = "button";
          sectionButton.className = [
            "section-link",
            depth === 1 ? "section-parent" : "section-child",
            `section-depth-${Math.min(depth, 4)}`,
            section.id === effectiveSection ? "is-active" : "",
          ].filter(Boolean).join(" ");
          sectionButton.textContent = section.title;
          sectionButton.addEventListener("click", () => {
            if (depth === 1 && section.id === activeRootId && section.id === effectiveSection) {
              if (collapsedSections.has(section.id)) {
                collapsedSections.delete(section.id);
              } else {
                collapsedSections.add(section.id);
              }
            }
            setRoute(targetTab, targetPage, section.id);
          });
          sectionList.appendChild(sectionButton);
        });
        pageList.appendChild(sectionList);
      }
    });
  }

  function renderFrame(activePage, anchor, query = "") {
    if (!activePage) {
      frame.removeAttribute("src");
      return;
    }
    let src = activePage.path;
    if (query) {
      src += `?q=${encodeURIComponent(query)}`;
    }
    if (anchor) {
      src += `#${encodeURIComponent(anchor)}`;
    }
    if (frame.getAttribute("src") !== src) {
      frame.setAttribute("src", src);
    }
  }

  function render() {
    if (!tabs.length) {
      return;
    }
    const route = parseRoute();
    const activeTab = findTab(route.tabDir);
    const activePage = findPage(activeTab, route.slug);
    renderTabs(activeTab);
    renderPages(activeTab, activePage, route.anchor);
    updateCurrent(activeTab, activePage, sectionTitle(activePage, route.anchor));
    renderFrame(activePage, route.anchor, route.q);
    if (!route.tabDir || !route.slug) {
      setRoute(activeTab, activePage);
    }
  }

  function sectionTitle(page, sectionId) {
    if (!page || !sectionId || !page.sections) {
      return "";
    }
    const section = page.sections.find((item) => item.id === sectionId);
    return section ? section.title : "";
  }

  function updateCurrent(tab, page, section = "") {
    if (!sidebarCurrent || !tab || !page) {
      return;
    }
    const sectionText = section ? `Section: ${section}` : `Page: ${page.title}`;
    sidebarCurrent.textContent = sectionText;
    sidebarCurrent.hidden = false;
  }

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      searchQuery = searchInput.value || "";
      render();
    });
  }

  window.addEventListener("message", (event) => {
    if (!event.data || event.data.type !== "doc-section-change") {
      return;
    }
    const route = parseRoute();
    const activeTab = findTab(route.tabDir);
    const activePage = findPage(activeTab, route.slug);
    const sectionId = event.data.sectionId || route.anchor || "";
    if (sectionId && route.tabDir && route.slug) {
      const params = new URLSearchParams();
      params.set("anchor", sectionId);
      if (route.q) {
        params.set("q", route.q);
      }
      const nextHash = `#/${activeTab.dir}/${activePage.slug}?${params.toString()}`;
      if (window.location.hash !== nextHash) {
        history.replaceState(null, "", nextHash);
      }
      renderPages(activeTab, activePage, sectionId);
    }
    updateCurrent(activeTab, activePage, event.data.section || "");
  });

  window.addEventListener("hashchange", render);
  render();
})();
