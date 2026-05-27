(function () {
  'use strict';

  var STORAGE_KEY = 'portalSidebarCollapsed';
  var layout = document.getElementById('portal-layout');
  if (!layout) return;

  function desktopMatches() {
    return window.matchMedia('(min-width: 992px)').matches;
  }

  function syncToggleTab() {
    var tab = layout.querySelector('.sidebar-toggle-tab');
    if (!tab) return;
    var collapsed = layout.classList.contains('sidebar-collapsed');
    tab.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    tab.setAttribute('aria-label', collapsed ? 'Öppna meny' : 'Stäng meny');
  }

  function applyCollapsedFromStorage() {
    if (!desktopMatches()) {
      layout.classList.remove('sidebar-collapsed');
      syncToggleTab();
      return;
    }
    try {
      layout.classList.toggle('sidebar-collapsed', localStorage.getItem(STORAGE_KEY) === '1');
    } catch (e) {}
    syncToggleTab();
  }

  function toggleSidebar() {
    if (!desktopMatches()) return;
    var next = !layout.classList.contains('sidebar-collapsed');
    layout.classList.toggle('sidebar-collapsed', next);
    try {
      localStorage.setItem(STORAGE_KEY, next ? '1' : '0');
    } catch (e) {}
    syncToggleTab();
  }

  document.addEventListener('DOMContentLoaded', function () {
    var tab = layout.querySelector('.sidebar-toggle-tab');
    if (tab) {
      syncToggleTab();
      tab.addEventListener('click', toggleSidebar);
    }
  });

  var mq = window.matchMedia('(min-width: 992px)');
  function onMqChange() {
    applyCollapsedFromStorage();
  }
  if (mq.addEventListener) {
    mq.addEventListener('change', onMqChange);
  } else if (mq.addListener) {
    mq.addListener(onMqChange);
  }
})();

function portalSearchEscapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function portalSearchEscapeRegExp(value) {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function portalSearchHighlightText(value, query) {
  var safe = portalSearchEscapeHtml(value);
  var term = (query || '').trim();
  if (!term) {
    return safe;
  }
  var pattern = new RegExp('(' + portalSearchEscapeRegExp(term) + ')', 'gi');
  return safe.replace(pattern, '<mark>$1</mark>');
}

function portalSearchApplyPageHighlights() {
  var page = document.querySelector('.global-search-results-page[data-search-query]');
  if (!page) {
    return;
  }
  var query = (page.getAttribute('data-search-query') || '').trim();
  if (query.length < 2) {
    return;
  }
  page.querySelectorAll('.global-search-highlightable').forEach(function (el) {
    el.innerHTML = portalSearchHighlightText(el.textContent, query);
  });
}

document.addEventListener('DOMContentLoaded', portalSearchApplyPageHighlights);

(function () {
  'use strict';

  var wrapper = document.querySelector('.portal-topbar-search[data-search-url]');
  var input = document.getElementById('portal-topbar-search-input');
  var resultsEl = document.getElementById('portal-global-search-results');
  if (!wrapper || !input || !resultsEl) return;

  var endpoint = wrapper.getAttribute('data-search-url');
  var resultsBaseUrl = wrapper.getAttribute('data-results-url');
  if (!endpoint) return;

  function buildResultsPageUrl(query) {
    if (!resultsBaseUrl) {
      return null;
    }
    return resultsBaseUrl + '?q=' + encodeURIComponent(query);
  }

  var debounceTimer = null;
  var activeController = null;
  var latestRequestId = 0;
  var lastPayload = null;
  var lastQuery = '';

  var TYPE_BADGES = {
    document: { label: 'Dokument', className: 'search-type-badge--document' },
    folder: { label: 'Mapp', className: 'search-type-badge--folder' },
    meeting: { label: 'Möte', className: 'search-type-badge--meeting' },
    matter: { label: 'Ärende', className: 'search-type-badge--matter' },
    property: { label: 'Fastighet', className: 'search-type-badge--property' },
    right_holder: { label: 'Rättighet', className: 'search-type-badge--right-holder' },
    calendar_event: { label: 'Kalender', className: 'search-type-badge--calendar' },
    fisheries_action: { label: 'Fiskevård', className: 'search-type-badge--fisheries' }
  };

  function renderTypeBadge(itemType) {
    var badge = TYPE_BADGES[itemType];
    if (!badge) {
      return '';
    }
    return (
      '<span class="search-type-badge ' + badge.className + '">' +
      portalSearchEscapeHtml(badge.label) +
      '</span>'
    );
  }

  function setExpanded(isExpanded) {
    input.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
  }

  function hideResults() {
    resultsEl.hidden = true;
    wrapper.classList.remove('is-open');
    setExpanded(false);
  }

  function showResults() {
    resultsEl.hidden = false;
    wrapper.classList.add('is-open');
    setExpanded(true);
  }

  function renderLoading() {
    resultsEl.innerHTML = '<div class="portal-global-search-results-scroll"><div class="portal-global-search-state">Söker...</div></div>';
    showResults();
  }

  function renderEmpty() {
    resultsEl.innerHTML = '<div class="portal-global-search-results-scroll"><div class="portal-global-search-state">Inga träffar</div></div>';
    showResults();
  }

  function renderResults(payload) {
    var groups = Array.isArray(payload && payload.groups) ? payload.groups : [];
    if (!groups.length) {
      renderEmpty();
      return;
    }

    var searchQuery = (payload && payload.query) || lastQuery;
    var html = '<div class="portal-global-search-results-scroll">';
    groups.forEach(function (group) {
      var items = Array.isArray(group.items) ? group.items : [];
      if (!items.length) return;
      html += '<section class="portal-global-search-group">';
      html += '<div class="portal-global-search-group-header">' + portalSearchEscapeHtml(group.label) + '</div>';
      html += '<div class="portal-global-search-items" role="listbox">';
      items.forEach(function (item) {
        html += '<a class="portal-global-search-item" href="' + portalSearchEscapeHtml(item.url) + '" data-result-url="' + portalSearchEscapeHtml(item.url) + '">';
        html += '<span class="portal-global-search-item-icon" aria-hidden="true"><i class="fa-solid ' + portalSearchEscapeHtml(item.icon || 'fa-magnifying-glass') + '"></i></span>';
        html += '<span class="portal-global-search-item-body">';
        html += '<span class="portal-global-search-item-title">' + portalSearchHighlightText(item.title, searchQuery) + '</span>';
        if (item.subtitle) {
          html += '<span class="portal-global-search-item-subtitle">' + portalSearchEscapeHtml(item.subtitle) + '</span>';
        }
        if (item.match) {
          html += '<span class="portal-global-search-match">Match: ' + portalSearchEscapeHtml(item.match) + '</span>';
        }
        if (item.snippet) {
          html += '<span class="portal-global-search-snippet">' + portalSearchHighlightText(item.snippet, searchQuery) + '</span>';
        }
        html += '</span>';
        html += renderTypeBadge(item.type);
        html += '</a>';
      });
      html += '</div></section>';
    });
    html += '</div>';

    if (searchQuery.length >= 2 && resultsBaseUrl) {
      var allResultsUrl = buildResultsPageUrl(searchQuery);
      if (allResultsUrl) {
        html += '<div class="portal-global-search-footer">';
        html += '<a class="portal-global-search-view-all" href="' + portalSearchEscapeHtml(allResultsUrl) + '">';
        html += '<span>Visa alla resultat för “' + portalSearchEscapeHtml(searchQuery) + '”</span>';
        html += '<i class="fa-solid fa-arrow-right portal-global-search-view-all-icon" aria-hidden="true"></i>';
        html += '</a></div>';
      }
    }

    resultsEl.innerHTML = html;
    showResults();
  }

  function runSearch(rawQuery) {
    var query = (rawQuery || '').trim();
    lastQuery = query;

    if (query.length < 2) {
      if (activeController) {
        activeController.abort();
        activeController = null;
      }
      hideResults();
      return;
    }

    if (activeController) {
      activeController.abort();
    }
    activeController = new AbortController();
    latestRequestId += 1;
    var requestId = latestRequestId;

    renderLoading();
    fetch(endpoint + '?q=' + encodeURIComponent(query), {
      method: 'GET',
      credentials: 'same-origin',
      signal: activeController.signal
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error('Search request failed');
        }
        return response.json();
      })
      .then(function (payload) {
        if (requestId !== latestRequestId) return;
        lastPayload = payload;
        renderResults(payload);
      })
      .catch(function (error) {
        if (error && error.name === 'AbortError') return;
        if (requestId !== latestRequestId) return;
        resultsEl.innerHTML = '<div class="portal-global-search-results-scroll"><div class="portal-global-search-state">Kunde inte hämta sökresultat</div></div>';
        showResults();
      })
      .finally(function () {
        if (requestId === latestRequestId) {
          activeController = null;
        }
      });
  }

  function debouncedSearch() {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
    debounceTimer = setTimeout(function () {
      runSearch(input.value);
    }, 250);
  }

  input.addEventListener('input', debouncedSearch);

  input.addEventListener('focus', function () {
    var query = (input.value || '').trim();
    if (query.length < 2) return;

    if (lastPayload && lastQuery === query) {
      renderResults(lastPayload);
      return;
    }
    runSearch(query);
  });

  input.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      hideResults();
      return;
    }
    if (event.key !== 'Enter') return;

    var query = (input.value || '').trim();
    if (query.length < 2) return;
    var resultsUrl = buildResultsPageUrl(query);
    if (!resultsUrl) return;
    event.preventDefault();
    window.location.href = resultsUrl;
  });

  resultsEl.addEventListener('click', function (event) {
    var item = event.target.closest('.portal-global-search-item');
    if (!item) return;
    hideResults();
  });

  document.addEventListener('click', function (event) {
    if (!wrapper.contains(event.target)) {
      hideResults();
    }
  });
})();
