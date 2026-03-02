#!/usr/bin/env python3
"""
TRITIUM-SC Comprehensive UI Button Audit
Clicks every interactive element and reports what happens.
"""

import os
import sys
import time
import json

OUT_DIR = os.path.join(os.path.dirname(__file__), '..', '.test-results', 'ui-audit')
os.makedirs(OUT_DIR, exist_ok=True)

from playwright.sync_api import sync_playwright

def screenshot(page, name):
    path = os.path.join(OUT_DIR, f'{name}.png')
    page.screenshot(path=path)
    print(f'  [SCREENSHOT] {name}.png')
    return path

def collect_console_errors(page, errors):
    """Attach a console listener to collect errors."""
    page.on('console', lambda msg: errors.append(f'{msg.type}: {msg.text}') if msg.type == 'error' else None)

def get_toast_text(page):
    """Get the text of any visible toast notification."""
    try:
        toast = page.locator('.toast-container .toast-message, .toast-container .toast, #toast-container > div').first
        if toast.is_visible(timeout=1000):
            return toast.text_content()
    except:
        pass
    return None

def get_cmd_status(page):
    """Get text from the command status area in unit inspector."""
    try:
        status = page.locator('.dc-cmd-status').first
        if status.is_visible(timeout=500):
            return status.text_content()
    except:
        pass
    return None

def main():
    results = []
    console_errors = []

    def record(name, action, result, detail=''):
        entry = {'name': name, 'action': action, 'result': result, 'detail': detail}
        results.append(entry)
        status_icon = 'OK' if result == 'pass' else 'WARN' if result == 'warn' else 'FAIL'
        print(f'  [{status_icon}] {name}: {action} -> {detail}')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        collect_console_errors(page, console_errors)

        # ============================================================
        # PHASE 1: Initial Load
        # ============================================================
        print('\n=== PHASE 1: Initial Page Load ===')
        page.goto('http://localhost:8000')
        page.wait_for_timeout(5000)
        screenshot(page, '01_initial_load')

        # Check basic elements loaded
        header = page.locator('#header-bar')
        record('Header Bar', 'Check visibility', 'pass' if header.is_visible() else 'fail',
               'Header bar is visible' if header.is_visible() else 'Header bar NOT visible')

        clock = page.locator('#header-clock')
        clock_text = clock.text_content() if clock.is_visible() else 'NOT VISIBLE'
        record('Clock', 'Check text', 'pass' if 'UTC' in clock_text else 'warn', f'Clock shows: {clock_text}')

        conn = page.locator('#connection-status')
        conn_text = conn.text_content() if conn.is_visible() else 'NOT VISIBLE'
        record('Connection Status', 'Check text', 'pass' if 'ONLINE' in conn_text else 'warn', f'Shows: {conn_text}')

        status_bar = page.locator('#status-bar')
        record('Status Bar', 'Check visibility', 'pass' if status_bar.is_visible() else 'fail',
               'Status bar is visible' if status_bar.is_visible() else 'Status bar NOT visible')

        # Check map mode buttons
        print('\n=== PHASE 1b: Map Mode Buttons ===')
        for mode in ['observe', 'tactical', 'setup']:
            btn = page.locator(f'[data-map-mode="{mode}"]')
            if btn.is_visible():
                btn.click()
                page.wait_for_timeout(500)
                is_active = 'active' in (btn.get_attribute('class') or '')
                record(f'Map Mode: {mode.upper()}', 'Click', 'pass' if is_active else 'warn',
                       f'Button {"has" if is_active else "missing"} active class')
            else:
                record(f'Map Mode: {mode.upper()}', 'Click', 'fail', 'Button not visible')

        # Reset to observe
        obs_btn = page.locator('[data-map-mode="observe"]')
        if obs_btn.is_visible():
            obs_btn.click()
            page.wait_for_timeout(300)

        screenshot(page, '02_map_modes_tested')

        # ============================================================
        # PHASE 2: Menu Bar
        # ============================================================
        print('\n=== PHASE 2: Menu Bar ===')

        menu_labels = ['FILE', 'VIEW', 'LAYOUT', 'MAP', 'GAME', 'HELP']
        for label in menu_labels:
            trigger = page.locator(f'.menu-trigger:has-text("{label}")')
            if trigger.is_visible():
                trigger.click()
                page.wait_for_timeout(400)

                # Check if dropdown appeared
                dropdown = trigger.locator('..').locator('.menu-dropdown')
                if dropdown.count() > 0 and not dropdown.first.is_hidden():
                    items = dropdown.first.locator('.menu-item')
                    item_count = items.count()
                    item_texts = []
                    for i in range(min(item_count, 8)):
                        txt = items.nth(i).text_content().strip()
                        if txt:
                            item_texts.append(txt)
                    record(f'Menu: {label}', 'Click to open', 'pass',
                           f'{item_count} items visible: {", ".join(item_texts[:5])}{"..." if len(item_texts) > 5 else ""}')
                    screenshot(page, f'03_menu_{label.lower()}')
                else:
                    record(f'Menu: {label}', 'Click to open', 'fail', 'Dropdown did not appear')
            else:
                record(f'Menu: {label}', 'Find trigger', 'fail', 'Menu trigger not found')

        # Close any open menu
        page.click('body', position={'x': 960, 'y': 540})
        page.wait_for_timeout(300)

        # Test MAP menu checkable toggles
        print('\n=== PHASE 2b: MAP Menu Toggles ===')
        map_trigger = page.locator('.menu-trigger:has-text("MAP")')
        if map_trigger.is_visible():
            map_trigger.click()
            page.wait_for_timeout(400)

            # Find checkable items and click one
            checkable_items = page.locator('.menu-item .menu-item-check')
            if checkable_items.count() > 0:
                # Click the "Satellite" toggle
                sat_item = page.locator('.menu-item:has-text("Satellite")')
                if sat_item.count() > 0:
                    sat_check_before = sat_item.first.locator('.menu-item-check').text_content()
                    sat_item.first.click()
                    page.wait_for_timeout(500)

                    # Re-open to verify state changed
                    map_trigger.click()
                    page.wait_for_timeout(400)
                    sat_check_after = page.locator('.menu-item:has-text("Satellite")').first.locator('.menu-item-check').text_content()

                    toggled = sat_check_before != sat_check_after
                    record('MAP > Satellite toggle', 'Click toggle', 'pass' if toggled else 'warn',
                           f'Check mark {"changed" if toggled else "unchanged"}: "{sat_check_before}" -> "{sat_check_after}"')
                else:
                    record('MAP > Satellite toggle', 'Find item', 'fail', 'Satellite item not found')
            else:
                record('MAP > Checkable items', 'Find items', 'fail', 'No checkable items found')

        # Close menu
        page.click('body', position={'x': 960, 'y': 540})
        page.wait_for_timeout(300)

        # Test GAME menu -> New Mission
        print('\n=== PHASE 2c: GAME Menu ===')
        game_trigger = page.locator('.menu-trigger:has-text("GAME")')
        if game_trigger.is_visible():
            game_trigger.click()
            page.wait_for_timeout(400)
            new_mission = page.locator('.menu-item:has-text("New Mission")')
            if new_mission.count() > 0:
                record('GAME > New Mission', 'Item present', 'pass', 'New Mission item found in GAME menu')
            else:
                record('GAME > New Mission', 'Item present', 'fail', 'Not found')

        # Close menu
        page.click('body', position={'x': 960, 'y': 540})
        page.wait_for_timeout(300)

        # Test HELP menu -> Keyboard Shortcuts
        print('\n=== PHASE 2d: HELP Menu ===')
        help_trigger = page.locator('.menu-trigger:has-text("HELP")')
        if help_trigger.is_visible():
            help_trigger.click()
            page.wait_for_timeout(400)
            about_item = page.locator('.menu-item:has-text("About")')
            if about_item.count() > 0:
                about_item.first.click()
                page.wait_for_timeout(500)
                record('HELP > About', 'Click', 'pass', 'About item clicked')
            else:
                record('HELP > About', 'Find item', 'fail', 'Not found')

        page.wait_for_timeout(300)

        # Test HELP > Keyboard Shortcuts
        help_trigger = page.locator('.menu-trigger:has-text("HELP")')
        if help_trigger.is_visible():
            help_trigger.click()
            page.wait_for_timeout(400)
            kb_item = page.locator('.menu-item:has-text("Keyboard Shortcuts")')
            if kb_item.count() > 0:
                kb_item.first.click()
                page.wait_for_timeout(500)
                help_overlay = page.locator('#help-overlay')
                is_visible = help_overlay.is_visible()
                record('HELP > Keyboard Shortcuts', 'Click', 'pass' if is_visible else 'warn',
                       f'Help overlay {"visible" if is_visible else "not visible"}')
                if is_visible:
                    screenshot(page, '04_help_overlay')
                    # Close it
                    page.press('body', 'Escape')
                    page.wait_for_timeout(300)

        # ============================================================
        # PHASE 3: Panel Toggle Buttons (command bar right side)
        # ============================================================
        print('\n=== PHASE 3: Command Bar Panel Buttons ===')

        panel_btns = page.locator('.command-bar-btn')
        panel_btn_count = panel_btns.count()
        record('Panel Toggle Buttons', 'Count', 'pass' if panel_btn_count > 0 else 'fail',
               f'{panel_btn_count} panel buttons found')

        for i in range(panel_btn_count):
            btn = panel_btns.nth(i)
            label = btn.text_content().strip()
            panel_id = btn.get_attribute('data-panel') or label
            was_active = 'active' in (btn.get_attribute('class') or '')

            btn.click()
            page.wait_for_timeout(500)

            is_active = 'active' in (btn.get_attribute('class') or '')
            toggled = was_active != is_active
            record(f'Panel Button: {label}', 'Click toggle',
                   'pass' if toggled else 'warn',
                   f'{"Opened" if is_active else "Closed"} panel (toggled={toggled})')

        screenshot(page, '05_panels_toggled')

        # Close all panels
        for i in range(panel_btns.count()):
            btn = panel_btns.nth(i)
            if 'active' in (btn.get_attribute('class') or ''):
                btn.click()
                page.wait_for_timeout(200)

        # ============================================================
        # PHASE 4: Keyboard Shortcuts for Panels
        # ============================================================
        print('\n=== PHASE 4: Keyboard Shortcuts ===')

        # Press '?' for help
        page.press('body', '?')
        page.wait_for_timeout(500)
        help_vis = page.locator('#help-overlay').is_visible()
        record('Keyboard: ?', 'Press key', 'pass' if help_vis else 'fail',
               f'Help overlay {"appeared" if help_vis else "did not appear"}')
        if help_vis:
            screenshot(page, '06_help_shortcut')
            page.press('body', 'Escape')
            page.wait_for_timeout(300)

        # Press '1' for Amy panel
        page.press('body', '1')
        page.wait_for_timeout(500)
        amy_panel = page.locator('.panel-header:has-text("AMY")')
        amy_vis = amy_panel.count() > 0 and amy_panel.first.is_visible()
        record('Keyboard: 1', 'Press key', 'pass' if amy_vis else 'warn',
               f'Amy panel {"visible" if amy_vis else "not visible"}')

        # Press '2' for Units panel
        page.press('body', '2')
        page.wait_for_timeout(500)
        units_panel = page.locator('.panel-header:has-text("UNIT")')
        units_vis = units_panel.count() > 0 and units_panel.first.is_visible()
        record('Keyboard: 2', 'Press key', 'pass' if units_vis else 'warn',
               f'Units panel {"visible" if units_vis else "not visible"}')

        # Press '4' for Game HUD
        page.press('body', '4')
        page.wait_for_timeout(500)
        game_panel = page.locator('.panel-header:has-text("GAME")')
        game_vis = game_panel.count() > 0 and game_panel.first.is_visible()
        record('Keyboard: 4', 'Press key', 'pass' if game_vis else 'warn',
               f'Game panel {"visible" if game_vis else "not visible"}')

        screenshot(page, '07_panels_via_keyboard')

        # Close panels
        page.press('body', '1')
        page.wait_for_timeout(200)
        page.press('body', '2')
        page.wait_for_timeout(200)
        page.press('body', '4')
        page.wait_for_timeout(200)

        # ============================================================
        # PHASE 5: Begin Battle
        # ============================================================
        print('\n=== PHASE 5: Begin Battle ===')

        # Check if BEGIN WAR button is visible
        begin_btn = page.locator('#war-begin-btn button, .war-begin-btn button')
        begin_visible = begin_btn.count() > 0 and begin_btn.first.is_visible()

        if begin_visible:
            record('BEGIN WAR Button', 'Check visibility', 'pass', 'BEGIN WAR button is visible')
            begin_btn.first.click()
            page.wait_for_timeout(2000)
            record('BEGIN WAR Button', 'Click', 'pass', 'Clicked BEGIN WAR button')
        else:
            # Try pressing 'B' key
            record('BEGIN WAR Button', 'Check visibility', 'warn', 'Button not visible, trying B key')
            page.press('body', 'b')
            page.wait_for_timeout(2000)
            record('Keyboard: B', 'Press key', 'pass', 'Pressed B to begin battle')

        screenshot(page, '08_battle_starting')

        # Check if a mission modal appeared
        modal = page.locator('#modal-overlay, .modal-overlay, .mission-modal')
        modal_vis = modal.count() > 0 and modal.first.is_visible()
        if modal_vis:
            record('Mission Modal', 'Check visibility', 'pass', 'Mission modal appeared')
            screenshot(page, '08b_mission_modal')

            # Look for mission items to click
            mission_items = page.locator('.mission-card, .mission-item, [data-mission]')
            if mission_items.count() > 0:
                mission_items.first.click()
                page.wait_for_timeout(500)
                record('Mission Selection', 'Click first mission', 'pass', f'Clicked mission (of {mission_items.count()} available)')
            else:
                record('Mission Selection', 'Find missions', 'warn', 'No mission items found in modal')

            # Look for a start/begin/launch button in the modal
            modal_btns = page.locator('.modal-content button, .mission-modal button')
            for i in range(modal_btns.count()):
                btn_text = modal_btns.nth(i).text_content().strip().upper()
                if any(kw in btn_text for kw in ['START', 'BEGIN', 'LAUNCH', 'DEPLOY', 'CONFIRM']):
                    modal_btns.nth(i).click()
                    page.wait_for_timeout(1000)
                    record('Mission Modal Start', 'Click start button', 'pass', f'Clicked button: {btn_text}')
                    break

            screenshot(page, '08c_after_mission_select')
        else:
            record('Mission Modal', 'Check visibility', 'warn', 'No mission modal appeared - game may have started directly')

        # Wait for battle to begin and units to spawn
        page.wait_for_timeout(5000)
        screenshot(page, '09_battle_running')

        # Check game score area
        score_area = page.locator('#game-score-area')
        score_visible = score_area.count() > 0 and score_area.is_visible()
        if score_visible:
            wave_text = page.locator('#game-wave').text_content()
            score_text = page.locator('#game-score').text_content()
            record('Game Score Area', 'Check after battle start', 'pass',
                   f'Wave: {wave_text}, Score: {score_text}')
        else:
            record('Game Score Area', 'Check after battle start', 'warn', 'Score area not visible')

        # Check unit/threat counts in header
        unit_count = page.locator('#header-units .stat-value').text_content()
        threat_count = page.locator('#header-threats .stat-value').text_content()
        record('Header Counters', 'Check after battle', 'pass',
               f'Units: {unit_count}, Threats: {threat_count}')

        # ============================================================
        # PHASE 6: Unit Inspector Panel
        # ============================================================
        print('\n=== PHASE 6: Unit Inspector ===')

        # Open the unit inspector panel via VIEW menu or keyboard '5'
        # First check if there is a command bar button for it
        inspector_btn = page.locator('.command-bar-btn[data-panel="unit-inspector"]')
        if inspector_btn.count() > 0 and inspector_btn.is_visible():
            inspector_btn.click()
            page.wait_for_timeout(500)
            record('Unit Inspector Panel', 'Open via button', 'pass', 'Clicked unit-inspector panel button')
        else:
            # Try via VIEW menu
            view_trigger = page.locator('.menu-trigger:has-text("VIEW")')
            if view_trigger.is_visible():
                view_trigger.click()
                page.wait_for_timeout(400)
                inspector_item = page.locator('.menu-item:has-text("INSPECTOR"), .menu-item:has-text("Inspector")')
                if inspector_item.count() > 0:
                    inspector_item.first.click()
                    page.wait_for_timeout(500)
                    record('Unit Inspector Panel', 'Open via VIEW menu', 'pass', 'Opened via menu')
                else:
                    # Just open units panel and try clicking a unit
                    page.click('body', position={'x': 960, 'y': 540})
                    page.wait_for_timeout(200)
                    record('Unit Inspector Panel', 'Open via menu', 'warn', 'Inspector not in VIEW menu')

        # Also open the Units panel
        page.press('body', '2')
        page.wait_for_timeout(500)
        screenshot(page, '10_units_panel_open')

        # ============================================================
        # PHASE 6b: Click Units in the Units Panel List
        # ============================================================
        print('\n=== PHASE 6b: Units Panel List ===')

        # Look for clickable unit rows in the units panel
        unit_rows = page.locator('.unit-row, .unit-item, [data-unit-id], .units-list-item')
        unit_row_count = unit_rows.count()
        record('Units Panel List', 'Find unit rows', 'pass' if unit_row_count > 0 else 'warn',
               f'{unit_row_count} unit rows found')

        if unit_row_count > 0:
            # Click the first unit row
            unit_rows.first.click()
            page.wait_for_timeout(500)
            first_unit_text = unit_rows.first.text_content().strip()[:60]
            record('Units Panel > First Unit', 'Click', 'pass', f'Clicked unit: {first_unit_text}')
            screenshot(page, '11_unit_selected_in_list')

            # Click second unit if available
            if unit_row_count > 1:
                unit_rows.nth(1).click()
                page.wait_for_timeout(500)
                second_unit_text = unit_rows.nth(1).text_content().strip()[:60]
                record('Units Panel > Second Unit', 'Click', 'pass', f'Clicked unit: {second_unit_text}')
                screenshot(page, '12_second_unit_selected')

        # ============================================================
        # PHASE 7: Click a Unit on the Map
        # ============================================================
        print('\n=== PHASE 7: Click Unit on Map ===')

        # Try to click on map units. The units are rendered on canvas/maplibre,
        # so we need to click where they are. Try map center area.
        # First check the canvas for unit markers
        canvas = page.locator('#tactical-canvas, .maplibregl-canvas')
        if canvas.count() > 0:
            # Click in center of map (where units likely are)
            bbox = canvas.first.bounding_box()
            if bbox:
                # Click a few spots around center to find a unit
                spots = [
                    (bbox['x'] + bbox['width'] * 0.5, bbox['y'] + bbox['height'] * 0.5),
                    (bbox['x'] + bbox['width'] * 0.4, bbox['y'] + bbox['height'] * 0.45),
                    (bbox['x'] + bbox['width'] * 0.55, bbox['y'] + bbox['height'] * 0.55),
                ]
                for sx, sy in spots:
                    page.mouse.click(sx, sy)
                    page.wait_for_timeout(500)

                record('Map Click', 'Click center area', 'pass', 'Clicked map in center area')
                screenshot(page, '13_map_clicked')

        # ============================================================
        # PHASE 8: Unit Inspector Controls (if a unit is selected)
        # ============================================================
        print('\n=== PHASE 8: Device Control Buttons ===')

        # Check if the unit inspector has device controls rendered
        dc_btns = page.locator('.dc-btn')
        dc_btn_count = dc_btns.count()

        if dc_btn_count == 0:
            # Try selecting a unit via units panel first
            unit_rows = page.locator('.unit-row, .unit-item, [data-unit-id], .units-list-item')
            if unit_rows.count() > 0:
                unit_rows.first.click()
                page.wait_for_timeout(800)
                dc_btns = page.locator('.dc-btn')
                dc_btn_count = dc_btns.count()

        record('Device Control Buttons', 'Count', 'pass' if dc_btn_count > 0 else 'warn',
               f'{dc_btn_count} device control buttons found')

        if dc_btn_count > 0:
            screenshot(page, '14_device_controls_visible')

            # Test each device control button
            for cmd_name in ['dispatch', 'patrol', 'recall', 'stop', 'fire', 'aim', 'auto', 'manual']:
                btn = page.locator(f'.dc-btn[data-cmd="{cmd_name}"]')
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click()
                    page.wait_for_timeout(600)
                    status_text = get_cmd_status(page) or '(no status text)'
                    record(f'DC Button: {cmd_name.upper()}', 'Click', 'pass', f'Status: {status_text}')
                    screenshot(page, f'15_dc_{cmd_name}')
                else:
                    record(f'DC Button: {cmd_name.upper()}', 'Find button', 'warn', 'Button not present for this unit type')

            # If in dispatch/patrol mode, press Escape to exit
            page.press('body', 'Escape')
            page.wait_for_timeout(300)

            # Test Lua command input
            cmd_input = page.locator('.dc-cmd-input')
            if cmd_input.count() > 0 and cmd_input.first.is_visible():
                cmd_input.first.fill('status()')
                send_btn = page.locator('.dc-btn[data-cmd="send"]')
                if send_btn.count() > 0:
                    send_btn.first.click()
                    page.wait_for_timeout(500)
                    status_text = get_cmd_status(page) or '(no status)'
                    record('Lua Command Input', 'Send status()', 'pass', f'Status: {status_text}')
                else:
                    record('Lua Command Input', 'Find SEND button', 'warn', 'SEND button not found')
            else:
                record('Lua Command Input', 'Find input', 'warn', 'Command input not visible')

        # ============================================================
        # PHASE 8b: Turret-specific Controls (PAN/TILT sliders)
        # ============================================================
        print('\n=== PHASE 8b: Turret Controls ===')

        # Try selecting a turret unit
        turret_selected = False

        # Check units panel for turret entries
        unit_rows = page.locator('.unit-row, .unit-item, [data-unit-id], .units-list-item')
        for i in range(unit_rows.count()):
            row_text = unit_rows.nth(i).text_content().lower()
            if 'turret' in row_text:
                unit_rows.nth(i).click()
                page.wait_for_timeout(800)
                turret_selected = True
                record('Turret Selection', 'Click turret in list', 'pass', f'Selected: {row_text.strip()[:40]}')
                break

        if not turret_selected:
            # Try the unit inspector type filter
            type_filter = page.locator('.ui-type-filter, select[data-bind="type-filter"]')
            if type_filter.count() > 0 and type_filter.first.is_visible():
                type_filter.first.select_option('turret')
                page.wait_for_timeout(500)
                record('Type Filter', 'Select turret', 'pass', 'Filtered to turret type')
                # Click next to select a turret
                next_btn = page.locator('[data-action="next"]')
                if next_btn.count() > 0:
                    next_btn.first.click()
                    page.wait_for_timeout(500)
                    turret_selected = True
                    record('Unit Inspector > Next', 'Navigate to turret', 'pass', 'Navigated to next turret')

        if turret_selected:
            screenshot(page, '16_turret_selected')

            # Look for PAN/TILT sliders
            pan_slider = page.locator('input[type="range"][data-axis="pan"], .dc-slider-pan, input.dc-pan')
            tilt_slider = page.locator('input[type="range"][data-axis="tilt"], .dc-slider-tilt, input.dc-tilt')

            if pan_slider.count() > 0:
                # Move the slider
                bbox = pan_slider.first.bounding_box()
                if bbox:
                    page.mouse.click(bbox['x'] + bbox['width'] * 0.7, bbox['y'] + bbox['height'] / 2)
                    page.wait_for_timeout(300)
                    val = pan_slider.first.input_value()
                    record('PAN Slider', 'Move to 70%', 'pass', f'Value: {val}')
                else:
                    record('PAN Slider', 'Get bounding box', 'warn', 'Could not get slider bbox')
            else:
                record('PAN Slider', 'Find slider', 'warn', 'Pan slider not found (may not be turret control)')

            if tilt_slider.count() > 0:
                bbox = tilt_slider.first.bounding_box()
                if bbox:
                    page.mouse.click(bbox['x'] + bbox['width'] * 0.3, bbox['y'] + bbox['height'] / 2)
                    page.wait_for_timeout(300)
                    val = tilt_slider.first.input_value()
                    record('TILT Slider', 'Move to 30%', 'pass', f'Value: {val}')
                else:
                    record('TILT Slider', 'Get bounding box', 'warn', 'Could not get slider bbox')
            else:
                record('TILT Slider', 'Find slider', 'warn', 'Tilt slider not found')

            screenshot(page, '17_turret_controls')
        else:
            record('Turret Selection', 'Find turret unit', 'warn', 'No turret units found in units list')

        # ============================================================
        # PHASE 9: Unit Inspector Navigation (prev/next)
        # ============================================================
        print('\n=== PHASE 9: Unit Inspector Navigation ===')

        prev_btn = page.locator('[data-action="prev"]')
        next_btn = page.locator('[data-action="next"]')

        if prev_btn.count() > 0 and prev_btn.first.is_visible():
            nav_label_before = page.locator('[data-bind="nav-label"]').text_content() if page.locator('[data-bind="nav-label"]').count() > 0 else '--'

            next_btn.first.click()
            page.wait_for_timeout(500)
            nav_label_after = page.locator('[data-bind="nav-label"]').text_content() if page.locator('[data-bind="nav-label"]').count() > 0 else '--'
            record('Unit Inspector > Next', 'Click', 'pass',
                   f'Nav changed: {nav_label_before} -> {nav_label_after}')

            prev_btn.first.click()
            page.wait_for_timeout(500)
            nav_label_back = page.locator('[data-bind="nav-label"]').text_content() if page.locator('[data-bind="nav-label"]').count() > 0 else '--'
            record('Unit Inspector > Prev', 'Click', 'pass',
                   f'Nav changed back: {nav_label_after} -> {nav_label_back}')

            screenshot(page, '18_inspector_navigation')
        else:
            record('Unit Inspector Nav', 'Find prev/next', 'warn', 'Navigation buttons not found')

        # ============================================================
        # PHASE 9b: Unit Inspector Filters
        # ============================================================
        print('\n=== PHASE 9b: Unit Inspector Filters ===')

        search_input = page.locator('.ui-search, input[data-bind="search"]')
        if search_input.count() > 0 and search_input.first.is_visible():
            search_input.first.fill('rover')
            page.wait_for_timeout(500)
            nav_after_search = page.locator('[data-bind="nav-label"]').text_content() if page.locator('[data-bind="nav-label"]').count() > 0 else '--'
            record('Unit Inspector > Search', 'Type "rover"', 'pass', f'Nav shows: {nav_after_search}')
            search_input.first.fill('')
            page.wait_for_timeout(300)
        else:
            record('Unit Inspector > Search', 'Find input', 'warn', 'Search input not visible')

        alliance_filter = page.locator('.ui-alliance-filter, select[data-bind="alliance-filter"]')
        if alliance_filter.count() > 0 and alliance_filter.first.is_visible():
            alliance_filter.first.select_option('friendly')
            page.wait_for_timeout(500)
            nav_friendly = page.locator('[data-bind="nav-label"]').text_content() if page.locator('[data-bind="nav-label"]').count() > 0 else '--'
            record('Unit Inspector > Alliance Filter', 'Set friendly', 'pass', f'Nav shows: {nav_friendly}')

            alliance_filter.first.select_option('hostile')
            page.wait_for_timeout(500)
            nav_hostile = page.locator('[data-bind="nav-label"]').text_content() if page.locator('[data-bind="nav-label"]').count() > 0 else '--'
            record('Unit Inspector > Alliance Filter', 'Set hostile', 'pass', f'Nav shows: {nav_hostile}')

            alliance_filter.first.select_option('ALL')
            page.wait_for_timeout(300)
        else:
            record('Unit Inspector > Alliance Filter', 'Find filter', 'warn', 'Alliance filter not visible')

        type_filter = page.locator('.ui-type-filter, select[data-bind="type-filter"]')
        if type_filter.count() > 0 and type_filter.first.is_visible():
            type_filter.first.select_option('drone')
            page.wait_for_timeout(500)
            nav_drone = page.locator('[data-bind="nav-label"]').text_content() if page.locator('[data-bind="nav-label"]').count() > 0 else '--'
            record('Unit Inspector > Type Filter', 'Set drone', 'pass', f'Nav shows: {nav_drone}')

            type_filter.first.select_option('ALL')
            page.wait_for_timeout(300)
        else:
            record('Unit Inspector > Type Filter', 'Find filter', 'warn', 'Type filter not visible')

        screenshot(page, '19_inspector_filters')

        # ============================================================
        # PHASE 10: Chat Panel
        # ============================================================
        print('\n=== PHASE 10: Chat Panel ===')

        # Open chat with 'C' key
        page.press('body', 'c')
        page.wait_for_timeout(800)

        chat_overlay = page.locator('#chat-overlay')
        chat_visible = chat_overlay.count() > 0 and chat_overlay.is_visible()
        record('Chat Panel', 'Open with C key', 'pass' if chat_visible else 'fail',
               f'Chat overlay {"visible" if chat_visible else "not visible"}')

        if chat_visible:
            screenshot(page, '20_chat_panel')

            # Type a message and send
            chat_input = page.locator('#chat-input')
            if chat_input.count() > 0:
                chat_input.fill('Hello Amy, status report')
                page.wait_for_timeout(300)

                send_btn = page.locator('#chat-send')
                if send_btn.count() > 0:
                    send_btn.click()
                    page.wait_for_timeout(2000)
                    record('Chat > Send Message', 'Click SEND', 'pass', 'Sent message to Amy')

                    # Check if messages appeared
                    messages = page.locator('#chat-messages .chat-msg, #chat-messages > div')
                    msg_count = messages.count()
                    record('Chat > Messages', 'Check after send', 'pass' if msg_count > 0 else 'warn',
                           f'{msg_count} messages in chat')
                    screenshot(page, '21_chat_sent')

            # Close chat
            close_btn = page.locator('#chat-close')
            if close_btn.count() > 0:
                close_btn.click()
                page.wait_for_timeout(300)
                record('Chat > Close', 'Click X', 'pass', 'Closed chat panel')

        # ============================================================
        # PHASE 11: Mode Indicator Button
        # ============================================================
        print('\n=== PHASE 11: Mode Indicator ===')

        mode_btn = page.locator('#mode-indicator')
        if mode_btn.count() > 0 and mode_btn.is_visible():
            mode_text = mode_btn.text_content().strip()
            mode_btn.click()
            page.wait_for_timeout(500)
            mode_text_after = mode_btn.text_content().strip()
            record('Mode Indicator', 'Click', 'pass',
                   f'Before: {mode_text}, After: {mode_text_after}')
        else:
            record('Mode Indicator', 'Find button', 'warn', 'Mode indicator not visible')

        # ============================================================
        # PHASE 12: Layout Shortcuts (Ctrl+1 through Ctrl+4)
        # ============================================================
        print('\n=== PHASE 12: Layout Shortcuts ===')

        for num, name in [('1', 'Commander'), ('2', 'Observer'), ('3', 'Tactical'), ('4', 'Battle')]:
            page.keyboard.press(f'Control+{num}')
            page.wait_for_timeout(800)
            # Check which panels are open
            active_panels = page.locator('.command-bar-btn.active')
            active_names = []
            for i in range(active_panels.count()):
                active_names.append(active_panels.nth(i).text_content().strip())
            record(f'Layout: Ctrl+{num} ({name})', 'Press shortcut', 'pass',
                   f'Active panels: {", ".join(active_names) if active_names else "none"}')

        screenshot(page, '22_layout_battle')

        # ============================================================
        # PHASE 13: GAME Over / Continued Battle State
        # ============================================================
        print('\n=== PHASE 13: Battle State Check ===')

        # Let battle run a bit more
        page.wait_for_timeout(3000)

        # Check war HUD elements
        elimination_feed = page.locator('#war-elimination-feed')
        if elimination_feed.count() > 0:
            feed_text = elimination_feed.text_content().strip()
            record('Elimination Feed', 'Check content', 'pass',
                   f'Content: {feed_text[:80] if feed_text else "(empty)"}')

        wave_banner = page.locator('#war-wave-banner')
        if wave_banner.count() > 0:
            banner_vis = wave_banner.is_visible()
            record('Wave Banner', 'Check visibility', 'pass',
                   f'{"Visible" if banner_vis else "Hidden"}: {wave_banner.text_content().strip()[:40]}')

        screenshot(page, '23_battle_state')

        # ============================================================
        # PHASE 14: VIEW Menu > Show All / Hide All
        # ============================================================
        print('\n=== PHASE 14: Show All / Hide All ===')

        view_trigger = page.locator('.menu-trigger:has-text("VIEW")')
        if view_trigger.is_visible():
            view_trigger.click()
            page.wait_for_timeout(400)

            show_all = page.locator('.menu-item:has-text("Show All")')
            if show_all.count() > 0:
                show_all.first.click()
                page.wait_for_timeout(800)
                active_after_show = page.locator('.command-bar-btn.active').count()
                record('VIEW > Show All', 'Click', 'pass', f'{active_after_show} panels now active')
                screenshot(page, '24_show_all')

            view_trigger.click()
            page.wait_for_timeout(400)
            hide_all = page.locator('.menu-item:has-text("Hide All")')
            if hide_all.count() > 0:
                hide_all.first.click()
                page.wait_for_timeout(800)
                active_after_hide = page.locator('.command-bar-btn.active').count()
                record('VIEW > Hide All', 'Click', 'pass', f'{active_after_hide} panels now active')
                screenshot(page, '25_hide_all')

        # ============================================================
        # PHASE 15: LAYOUT Menu Items
        # ============================================================
        print('\n=== PHASE 15: Layout Menu Items ===')

        layout_trigger = page.locator('.menu-trigger:has-text("LAYOUT")')
        if layout_trigger.is_visible():
            layout_trigger.click()
            page.wait_for_timeout(400)

            layout_items = page.locator('.menu-dropdown:not([hidden]) .menu-item')
            layout_names = []
            for i in range(layout_items.count()):
                txt = layout_items.nth(i).text_content().strip()
                if txt and 'Save' not in txt:
                    layout_names.append(txt)
            record('LAYOUT Menu', 'List items', 'pass', f'Layouts: {", ".join(layout_names)}')

            # Click the first layout
            if layout_items.count() > 0:
                first_layout_text = layout_items.first.text_content().strip()
                layout_items.first.click()
                page.wait_for_timeout(800)
                record(f'LAYOUT > {first_layout_text}', 'Apply layout', 'pass', 'Layout applied')

        page.click('body', position={'x': 960, 'y': 540})
        page.wait_for_timeout(300)

        # ============================================================
        # PHASE 16: FILE Menu > Save/Export/Import
        # ============================================================
        print('\n=== PHASE 16: FILE Menu ===')

        file_trigger = page.locator('.menu-trigger:has-text("FILE")')
        if file_trigger.is_visible():
            file_trigger.click()
            page.wait_for_timeout(400)

            save_item = page.locator('.menu-item:has-text("Save Layout")')
            if save_item.count() > 0:
                save_item.first.click()
                page.wait_for_timeout(500)
                save_input = page.locator('.command-bar-save-input')
                if save_input.count() > 0 and save_input.first.is_visible():
                    record('FILE > Save Layout', 'Open save input', 'pass', 'Save input appeared')
                    save_input.first.fill('test-layout')
                    save_input.first.press('Enter')
                    page.wait_for_timeout(500)
                    record('FILE > Save Layout', 'Save as "test-layout"', 'pass', 'Layout saved')
                else:
                    record('FILE > Save Layout', 'Open save input', 'warn', 'Save input did not appear')

        page.click('body', position={'x': 960, 'y': 540})
        page.wait_for_timeout(300)

        # ============================================================
        # PHASE 17: Context Menu (right-click on map)
        # ============================================================
        print('\n=== PHASE 17: Context Menu ===')

        canvas = page.locator('.maplibregl-canvas, #tactical-canvas')
        if canvas.count() > 0:
            bbox = canvas.first.bounding_box()
            if bbox:
                page.mouse.click(bbox['x'] + bbox['width'] / 2, bbox['y'] + bbox['height'] / 2,
                                button='right')
                page.wait_for_timeout(500)

                ctx_menu = page.locator('.context-menu, .map-context-menu, [data-component="context-menu"]')
                if ctx_menu.count() > 0 and ctx_menu.first.is_visible():
                    ctx_items = ctx_menu.first.locator('.ctx-item, .context-menu-item, button, div[role="menuitem"]')
                    item_names = []
                    for i in range(ctx_items.count()):
                        txt = ctx_items.nth(i).text_content().strip()
                        if txt:
                            item_names.append(txt)
                    record('Context Menu', 'Right-click map', 'pass',
                           f'{ctx_items.count()} items: {", ".join(item_names[:5])}')
                    screenshot(page, '26_context_menu')

                    # Click first item
                    if ctx_items.count() > 0:
                        ctx_items.first.click()
                        page.wait_for_timeout(500)
                        record('Context Menu > First Item', 'Click', 'pass',
                               f'Clicked: {item_names[0] if item_names else "unknown"}')
                else:
                    record('Context Menu', 'Right-click map', 'warn', 'No context menu appeared')
        else:
            record('Context Menu', 'Find canvas', 'fail', 'Map canvas not found')

        # ============================================================
        # PHASE 18: Game HUD Panel Details
        # ============================================================
        print('\n=== PHASE 18: Game HUD Panel ===')

        page.press('body', '4')
        page.wait_for_timeout(500)

        game_hud = page.locator('.panel-header:has-text("GAME")')
        if game_hud.count() > 0 and game_hud.first.is_visible():
            screenshot(page, '27_game_hud_panel')

            # Check for begin war button or wave info in the panel
            game_content = page.locator('[data-panel-id="game"] .panel-body, .ghud-body')
            if game_content.count() > 0:
                content_text = game_content.first.text_content().strip()[:200]
                record('Game HUD Panel', 'Check content', 'pass', f'Content: {content_text}')

            # Look for buttons in game HUD
            game_btns = page.locator('[data-panel-id="game"] button, .ghud-body button')
            for i in range(game_btns.count()):
                btn_text = game_btns.nth(i).text_content().strip()
                if btn_text:
                    record(f'Game HUD Button', 'Found', 'pass', f'Button: {btn_text}')
        else:
            record('Game HUD Panel', 'Open', 'warn', 'Game HUD panel not visible')

        page.press('body', '4')
        page.wait_for_timeout(200)

        # ============================================================
        # PHASE 19: Final State Screenshot
        # ============================================================
        print('\n=== PHASE 19: Final State ===')
        screenshot(page, '28_final_state')

        # ============================================================
        # Summary
        # ============================================================
        print('\n' + '='*72)
        print('UI AUDIT SUMMARY')
        print('='*72)

        pass_count = sum(1 for r in results if r['result'] == 'pass')
        warn_count = sum(1 for r in results if r['result'] == 'warn')
        fail_count = sum(1 for r in results if r['result'] == 'fail')
        total = len(results)

        print(f'\nTotal checks: {total}')
        print(f'  PASS: {pass_count}')
        print(f'  WARN: {warn_count}')
        print(f'  FAIL: {fail_count}')

        if console_errors:
            print(f'\nConsole Errors ({len(console_errors)}):')
            for err in console_errors[:20]:
                print(f'  {err[:120]}')

        print('\n--- Detail Report ---')
        for r in results:
            status = 'OK  ' if r['result'] == 'pass' else 'WARN' if r['result'] == 'warn' else 'FAIL'
            print(f'[{status}] {r["name"]}: {r["action"]} -- {r["detail"]}')

        # Save JSON report
        report = {
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'summary': {'total': total, 'pass': pass_count, 'warn': warn_count, 'fail': fail_count},
            'console_errors': console_errors[:50],
            'results': results,
        }
        report_path = os.path.join(OUT_DIR, 'audit_report.json')
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        print(f'\nJSON report saved to: {report_path}')
        print(f'Screenshots saved to: {OUT_DIR}/')

        # Keep browser open briefly for visual inspection
        page.wait_for_timeout(3000)
        browser.close()

    return fail_count == 0

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
