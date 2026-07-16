// ==UserScript==
// @name         Find a Grave - Iterative Search Pro
// @namespace    http://tampermonkey.net/
// @version      4.0
// @description  URL-based iterative search, safe countdowns, and reliable date filtering.
// @author       You
// @match        *://www.findagrave.com/*
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    // ==========================================
    // 1. STATE MANAGEMENT
    // ==========================================
    const State = {
        load: () => JSON.parse(sessionStorage.getItem('fag_search_state') || '{"active":false, "first":"", "last":"", "step":0, "context":"none", "auto":true}'),
        save: (data) => sessionStorage.setItem('fag_search_state', JSON.stringify(data)),
        reset: () => sessionStorage.removeItem('fag_search_state')
    };

    // ==========================================
    // 2. SEARCH STRATEGIES (URL BUILDER)
    // ==========================================
    // By building the URL directly, we completely bypass FindaGrave's React UI blocking our inputs.
    const Strategies = [
        {
            name: "1. Exact Match (Sniper)",
            apply: (url, f, l) => {
                url.searchParams.set('firstname', f);
                url.searchParams.set('lastname', l);
                url.searchParams.delete('fuzzyNames');
            }
        },
        {
            name: "2. Fuzzy Match (Net Caster)",
            apply: (url, f, l) => {
                url.searchParams.set('firstname', f);
                url.searchParams.set('lastname', l);
                url.searchParams.set('fuzzyNames', 'true');
            }
        },
        {
            name: "3. First Initial + Fuzzy",
            apply: (url, f, l) => {
                const initial = f.length > 0 ? f.substring(0, 1) + '*' : '';
                url.searchParams.set('firstname', initial);
                url.searchParams.set('lastname', l);
                url.searchParams.set('fuzzyNames', 'true');
            }
        },
        {
            name: "4. Vowel Trap Bypass",
            apply: (url, f, l) => {
                const fuzzyLast = l ? l.replace(/[aeiouyAEIOUY]/, '*') : ''; // Replaces first vowel only
                url.searchParams.set('firstname', f);
                url.searchParams.set('lastname', fuzzyLast);
                url.searchParams.set('fuzzyNames', 'true');
            }
        },
        {
            name: "5. Last Name Only",
            apply: (url, f, l) => {
                url.searchParams.set('firstname', '');
                url.searchParams.set('lastname', l);
                url.searchParams.set('fuzzyNames', 'true');
            }
        }
    ];

    const Contexts = {
        none: (url) => {},
        civilWarBroad: (url) => {
            // Broad search: Veteran flag + Birth Range (1800 to 1850) - NO bio keywords to ruin the search
            url.searchParams.set('isVeteran', 'true');
            url.searchParams.set('birthyear', '1825');
            url.searchParams.set('birthyearfilter', '25'); // +/- 25 years
        },
        civilWarBio: (url) => {
            // Strict search: Looks specifically for Civil War terms in the bio, ignoring strict dates
            url.searchParams.set('isVeteran', 'true');
            url.searchParams.set('bio', '"Civil War" OR "CSA" OR "GAR"');
        }
    };

    const runIteration = () => {
        const state = State.load();
        if (!state.active) return;

        let url = new URL("https://www.findagrave.com/memorial/search");

        // Base params to clear the slate
        url.searchParams.set('fulltext', '');

        // Apply Strategy
        const strategy = Strategies[state.step];
        if (strategy) strategy.apply(url, state.first, state.last);

        // Apply Context Filters
        if (Contexts[state.context]) Contexts[state.context](url);

        // Navigate
        window.location.href = url.toString();
    };

    // ==========================================
    // 3. UI LOGIC (Control Panel)
    // ==========================================
    const UI = {
        renderPanel: () => {
            if (document.getElementById('fag-helper-panel')) return;

            const state = State.load();

            const panel = document.createElement('div');
            panel.id = 'fag-helper-panel';
            panel.style.cssText = `
                position: fixed; bottom: 20px; left: 20px;
                background: #f8f9fa; border: 1px solid #ccc; border-radius: 6px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.2); z-index: 9999; width: 320px;
                font-family: monospace; color: #333; transition: all 0.3s ease;
            `;

            panel.innerHTML = `
                <div id="fag-header" style="display: flex; justify-content: space-between; padding: 10px; background: #343a40; color: white; cursor: pointer; border-radius: 6px 6px 0 0; font-weight: bold;">
                    <span>Iterative Search Pro</span>
                    <span id="fag-toggle">▼</span>
                </div>
                <div id="fag-content" style="padding: 15px;">
                    <input type="text" id="fag-first" placeholder="First Name" value="${state.first}" style="width: 100%; margin-bottom: 5px; padding: 5px; box-sizing: border-box;">
                    <input type="text" id="fag-last" placeholder="Last Name" value="${state.last}" style="width: 100%; margin-bottom: 10px; padding: 5px; box-sizing: border-box;">

                    <select id="fag-context" style="width: 100%; margin-bottom: 10px; padding: 5px; box-sizing: border-box;">
                        <option value="none" ${state.context === 'none' ? 'selected' : ''}>Standard Context</option>
                        <option value="civilWarBroad" ${state.context === 'civilWarBroad' ? 'selected' : ''}>Civil War (Dates 1800-1850 + Vet)</option>
                        <option value="civilWarBio" ${state.context === 'civilWarBio' ? 'selected' : ''}>Civil War (Bio Keywords + Vet)</option>
                    </select>

                    <label style="display: block; margin-bottom: 10px; font-size: 0.9em; cursor: pointer;">
                        <input type="checkbox" id="fag-auto" ${state.auto ? 'checked' : ''}>
                        Auto-Advance on 0 Results
                    </label>

                    <div id="fag-status-text" style="font-size: 0.9em; margin-bottom: 10px; font-weight: bold; color: #007bff;">
                        ${state.active ? `Last Run: ${Strategies[state.step]?.name || 'Finished'}` : 'Idle'}
                    </div>

                    <div style="display: flex; gap: 5px;">
                        <button id="fag-btn-start" style="flex: 1; padding: 8px; background: #28a745; color: white; border: none; cursor: pointer; border-radius: 4px;">
                            ${state.active ? 'Next Strategy ➔' : 'Start Search'}
                        </button>
                        <button id="fag-btn-stop" style="flex: 1; padding: 8px; background: #dc3545; color: white; border: none; cursor: pointer; display: ${state.active ? 'block' : 'none'}; border-radius: 4px;">
                            Stop / Reset
                        </button>
                    </div>
                </div>
            `;

            document.body.appendChild(panel);

            // Handle Checkbox State
            document.getElementById('fag-auto').onchange = (e) => {
                const currentState = State.load();
                currentState.auto = e.target.checked;
                State.save(currentState);
            };

            // Start / Next Logic
            document.getElementById('fag-btn-start').onclick = () => {
                const currentState = State.load();

                if (!currentState.active) {
                    currentState.active = true;
                    currentState.first = document.getElementById('fag-first').value;
                    currentState.last = document.getElementById('fag-last').value;
                    currentState.context = document.getElementById('fag-context').value;
                    currentState.auto = document.getElementById('fag-auto').checked;
                    currentState.step = 0;
                } else {
                    currentState.step++;
                    if (currentState.step >= Strategies.length) {
                        alert('All strategies exhausted for this name.');
                        State.reset();
                        location.reload();
                        return;
                    }
                }

                State.save(currentState);
                runIteration();
            };

            // Stop Logic
            document.getElementById('fag-btn-stop').onclick = () => {
                // Clear any active countdown timers attached to window
                if (window.fagTimer) clearInterval(window.fagTimer);
                State.reset();
                window.location.href = "https://www.findagrave.com/memorial/search";
            };

            // Toggle Collapse
            let isCollapsed = false;
            document.getElementById('fag-header').onclick = () => {
                isCollapsed = !isCollapsed;
                document.getElementById('fag-content').style.display = isCollapsed ? 'none' : 'block';
                document.getElementById('fag-toggle').style.transform = isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)';
            };
        }
    };

    // ==========================================
    // 4. INITIALIZATION & COUNTDOWN TIMER
    // ==========================================
    const init = () => {
        if (document.querySelector('form') || window.location.href.includes('search')) {
            UI.renderPanel();

            const state = State.load();
            if (state.active) {
                const pageText = document.body.innerText || "";

                // Only trigger if auto-advance is checked AND zero results are found
                if (state.auto && pageText.includes("No matches found for")) {
                    let countdown = 5;
                    const statusEl = document.getElementById('fag-status-text');

                    window.fagTimer = setInterval(() => {
                        statusEl.style.color = "#dc3545"; // Make text red
                        statusEl.textContent = `Zero results. Advancing in ${countdown}s...`;
                        countdown--;

                        if (countdown < 0) {
                            clearInterval(window.fagTimer);
                            document.getElementById('fag-btn-start').click(); // Proceed to next
                        }
                    }, 1000);
                }
            }
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();