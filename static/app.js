// ── Player Search ────────────────────────────────────────────────────────────

const searchInput = document.getElementById('playerSearch');
const searchForm = document.getElementById('searchForm');
const searchIdField = document.getElementById('searchPlayerId');
const searchDropdown = document.getElementById('searchDropdown');

let searchCache = [];
let activeIdx = -1;

if (searchInput) {
    let debounce;
    searchInput.addEventListener('input', function () {
        clearTimeout(debounce);
        const q = this.value.trim();
        if (q.length < 2) {
            searchDropdown.classList.remove('show');
            return;
        }
        debounce = setTimeout(async () => {
            const resp = await fetch(`/api/players?q=${encodeURIComponent(q)}`);
            searchCache = await resp.json();
            activeIdx = -1;
            renderDropdown();
        }, 200);
    });

    searchInput.addEventListener('keydown', function (e) {
        const items = searchDropdown.querySelectorAll('.search-item');
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            activeIdx = Math.min(activeIdx + 1, items.length - 1);
            updateActive(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            activeIdx = Math.max(activeIdx - 1, 0);
            updateActive(items);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (activeIdx >= 0 && activeIdx < searchCache.length) {
                selectPlayer(searchCache[activeIdx]);
            }
        } else if (e.key === 'Escape') {
            searchDropdown.classList.remove('show');
        }
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', function (e) {
        if (!e.target.closest('#searchForm')) {
            searchDropdown.classList.remove('show');
        }
    });

    searchInput.addEventListener('focus', function () {
        if (searchCache.length > 0 && this.value.trim().length >= 2) {
            searchDropdown.classList.add('show');
        }
    });
}

function renderDropdown() {
    if (searchCache.length === 0) {
        searchDropdown.innerHTML = '<div class="search-item"><span class="si-meta">No results found</span></div>';
        searchDropdown.classList.add('show');
        return;
    }
    searchDropdown.innerHTML = searchCache.map((p, i) => `
        <div class="search-item ${i === activeIdx ? 'active' : ''}" data-idx="${i}">
            <span class="si-rank">#${p.rank}</span>
            <span class="si-name">${p.name}</span>
            <span class="si-meta">${p.pos} · ${p.school}${p.conference ? ' · ' + p.conference : ''}</span>
        </div>
    `).join('');

    searchDropdown.querySelectorAll('.search-item').forEach(item => {
        item.addEventListener('click', () => {
            const idx = parseInt(item.dataset.idx);
            selectPlayer(searchCache[idx]);
        });
        item.addEventListener('mouseenter', () => {
            activeIdx = parseInt(item.dataset.idx);
            updateActive(searchDropdown.querySelectorAll('.search-item'));
        });
    });

    searchDropdown.classList.add('show');
}

function updateActive(items) {
    items.forEach((el, i) => el.classList.toggle('active', i === activeIdx));
}

function selectPlayer(p) {
    searchIdField.value = p.id;
    searchInput.value = p.name;
    searchDropdown.classList.remove('show');
    searchForm.submit();
}

// ── Notes auto-save ──────────────────────────────────────────────────────────

document.querySelectorAll('.notes-area').forEach(textarea => {
    let timeout;
    textarea.addEventListener('input', function () {
        clearTimeout(timeout);
        const pid = this.dataset.playerId;
        const content = this.value;
        timeout = setTimeout(async () => {
            await fetch(`/api/notes/${pid}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content }),
            });
            // Show brief save indicator
            const indicator = this.parentElement.querySelector('.save-indicator');
            if (indicator) {
                indicator.textContent = 'Saved';
                indicator.style.opacity = 1;
                setTimeout(() => indicator.style.opacity = 0, 1500);
            }
        }, 800);
    });
});

// ── Watchlist toggle ─────────────────────────────────────────────────────────

document.querySelectorAll('.btn-watch').forEach(btn => {
    btn.addEventListener('click', async function () {
        const pid = this.dataset.playerId;
        const isWatched = this.dataset.watched === 'true';
        const method = isWatched ? 'DELETE' : 'POST';
        await fetch(`/api/watchlist/${pid}`, { method });
        this.dataset.watched = (!isWatched).toString();
        this.textContent = isWatched ? '☆ Watch' : '★ Watching';
        this.classList.toggle('btn-warning', !isWatched);
        this.classList.toggle('btn-outline-secondary', isWatched);
    });
});

// ── Watchlist remove ─────────────────────────────────────────────────────────

document.querySelectorAll('.btn-wl-remove').forEach(btn => {
    btn.addEventListener('click', async function () {
        const pid = this.dataset.playerId;
        await fetch(`/api/watchlist/${pid}`, { method: 'DELETE' });
        const card = this.closest('.wl-card');
        if (card) card.remove();
    });
});

// ── Client-side table filtering ──────────────────────────────────────────────

function initFilters(tableId, ...filterIds) {
    const table = document.getElementById(tableId);
    if (!table) return;
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));

    filterIds.forEach(fid => {
        const sel = document.getElementById(fid);
        if (!sel) return;
        sel.addEventListener('change', () => applyFilters());
    });

    function applyFilters() {
        rows.forEach(row => {
            let show = true;
            filterIds.forEach(fid => {
                const sel = document.getElementById(fid);
                if (!sel || sel.value === 'All') return;
                const col = sel.dataset.col;
                const cell = row.querySelector(`td[data-col="${col}"]`);
                if (cell && cell.textContent.trim() !== sel.value) show = false;
            });
            row.style.display = show ? '' : 'none';
        });
    }
}

// ── Scarcity archetype search ────────────────────────────────────────────────

const archSearch = document.getElementById('archSearch');
if (archSearch) {
    archSearch.addEventListener('input', function () {
        const q = this.value.toLowerCase().trim();
        document.querySelectorAll('.arch-guide').forEach(card => {
            const text = card.textContent.toLowerCase();
            card.style.display = (!q || text.includes(q)) ? '' : 'none';
        });
    });
}
