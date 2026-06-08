// ==UserScript==
// @name         Find A Grave Ambient Scraper
// @namespace    http://tampermonkey.net/
// @version      0.5
// @description  Manual scraper with safe export and clear functionality
// @match        https://www.findagrave.com/memorial/*
// @grant        GM_setValue
// @grant        GM_getValue
// @run-at       document-end
// ==/UserScript==

(function() {
    'use strict';

    // --- 1. Core Logic: Extraction ---
    function extractMemorialData() {
        const url = window.location.href;
        const memorial_id = url.match(/\/memorial\/(\d+)\//)?.[1] || "Unknown";
        
        const safeText = (selector, context = document) => {
            const el = context.querySelector(selector);
            return el ? el.innerText.trim() : "";
        };

        const extractFamilyLinks = (relationshipText) => {
            const names = [];
            const headers = Array.from(document.querySelectorAll('h3, h4, b'));
            const header = headers.find(h => h.innerText && h.innerText.includes(relationshipText));
            
            if (!header) return names;

            let nextEl = header.nextElementSibling;
            while (nextEl && !['H3', 'H4', 'B'].includes(nextEl.tagName)) {
                const links = nextEl.querySelectorAll('a[href*="/memorial/"]');
                links.forEach(link => {
                    let cleanName = link.innerText.replace(/\d{4}\s*–\s*\d{4}/g, '').trim();
                    if (cleanName && !cleanName.includes("Remove Ads") && !cleanName.includes("@")) {
                        names.push(cleanName);
                    }
                });
                nextEl = nextEl.nextElementSibling;
            }
            return names;
        };

        let rawDeathDate = safeText('[itemprop="deathDate"]') || safeText('.death-date');
        let deathDate = rawDeathDate.replace(/\(aged\s*\d+\)/i, '').trim();
        
        let bio = safeText('[itemprop="description"]') || safeText('.bio-text');
        bio = bio.replace(/Read More$/i, '').trim();
        bio = bio.replace(/…$/, '').trim();

        return {
            memorial_id: memorial_id,
            name: document.querySelector('h1')?.innerText.trim() || "Unknown",
            url: url,
            birth_date: safeText('[itemprop="birthDate"]') || safeText('.birth-date'),
            birth_location: safeText('[itemprop="birthPlace"]'),
            death_date: deathDate,
            death_age: parseInt(rawDeathDate.match(/aged\s*(\d+)/i)?.[1]) || null,
            death_location: safeText('[itemprop="deathPlace"]'),
            burial_cemetery: safeText('[itemprop="cemetery"], #cemetery-name'),
            burial_location: safeText('.cemetery-location'),
            biography: bio,
            family_parents: extractFamilyLinks('Parents'),
            family_spouse: extractFamilyLinks('Spouse').join(', '), 
            family_children: extractFamilyLinks('Children'),
            scraped_at: new Date().toISOString()
        };
    }

    // --- 2. Storage Logic: State Management ---
    function saveToLedger(data) {
        let ledger = GM_getValue('memorial_ledger', []);
        
        const index = ledger.findIndex(entry => entry.memorial_id === data.memorial_id);
        if (index > -1) {
            ledger[index] = data;
            console.log(`[Scraper] Updated ${data.name}.`);
        } else {
            ledger.push(data);
            console.log(`[Scraper] Saved ${data.name}. Total records: ${ledger.length}`);
        }
        
        GM_setValue('memorial_ledger', ledger);
        updateUI();
    }

    function exportLedger() {
        const ledger = GM_getValue('memorial_ledger', []);
        
        if (ledger.length === 0) {
            alert("No data to export!");
            return;
        }

        const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(ledger, null, 2));
        
        const downloadAnchorNode = document.createElement('a');
        downloadAnchorNode.setAttribute("href", dataStr);
        downloadAnchorNode.setAttribute("download", "memorials_archive.json");
        document.body.appendChild(downloadAnchorNode); 
        downloadAnchorNode.click();
        downloadAnchorNode.remove();

        // Safety prompt to clear data after export triggers
        setTimeout(() => {
            if (confirm("Export triggered! Would you like to clear the stored data to start a new batch?")) {
                GM_setValue('memorial_ledger', []);
                updateUI();
                console.log("[Scraper] Ledger cleared.");
            }
        }, 500);
    }

    // --- 3. UI Logic: Floating Control Panel ---
    function updateUI() {
        const currentCount = GM_getValue('memorial_ledger', []).length;
        const exportBtn = document.getElementById('fag-export-btn');
        if (exportBtn) {
            exportBtn.innerText = `Export Data (${currentCount})`;
        }
    }

    function injectControlPanel() {
        if (document.getElementById('fag-control-panel')) return;

        const panel = document.createElement('div');
        panel.id = 'fag-control-panel';
        panel.style.cssText = `
            position: fixed; 
            bottom: 20px; 
            right: 20px; 
            z-index: 999999; 
            background: #1e1e1e; 
            border: 1px solid #444; 
            border-radius: 6px;
            padding: 10px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            font-family: monospace;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        `;

        const scrapeBtn = document.createElement('button');
        scrapeBtn.innerText = "Scrape Current Page";
        scrapeBtn.style.cssText = `
            padding: 8px 12px; 
            background: #28a745; 
            color: #fff; 
            border: none; 
            border-radius: 4px;
            cursor: pointer;
            font-weight: bold;
        `;
        scrapeBtn.onclick = () => {
            const data = extractMemorialData();
            if (data.memorial_id !== "Unknown") {
                saveToLedger(data);
                scrapeBtn.innerText = "Scraped!";
                scrapeBtn.style.background = "#20c997";
                setTimeout(() => {
                    scrapeBtn.innerText = "Scrape Current Page";
                    scrapeBtn.style.background = "#28a745";
                }, 2000);
            }
        };

        const currentCount = GM_getValue('memorial_ledger', []).length;
        const exportBtn = document.createElement('button');
        exportBtn.id = 'fag-export-btn';
        exportBtn.innerText = `Export Data (${currentCount})`;
        exportBtn.style.cssText = `
            padding: 8px 12px; 
            background: #495057; 
            color: #fff; 
            border: none; 
            border-radius: 4px;
            cursor: pointer;
        `;
        exportBtn.onclick = exportLedger;

        panel.appendChild(scrapeBtn);
        panel.appendChild(exportBtn);
        document.body.appendChild(panel);
    }

    // --- Initialization ---
    function init() {
        injectControlPanel();
    }

    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        init();
    } else {
        document.addEventListener('DOMContentLoaded', init);
    }
})();