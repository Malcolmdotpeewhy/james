"""
Automate the creation of 46 new schedule entries on jules.google.com/session.
This script uses Playwright to duplicate an existing 5:30 AM task, increment
the time by 30 minutes for each iteration, and save it.

IMPORTANT: Because the script is running against an external UI where the
exact DOM structure is unknown, you MUST update the CSS/XPath selectors
(marked with `TODO: UPDATE SELECTOR`) using your browser's developer tools
to match the actual elements on the page.
"""
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        # Launch browser (set headless=False so you can see what's happening and log in if needed)
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # 1. Navigate to the target URL
        print("Navigating to https://jules.google.com/session...")
        page.goto("https://jules.google.com/session")

        # Give you time to log in if there's an authentication screen
        print("Please log in if required. Waiting 15 seconds...")
        page.wait_for_timeout(15000)

        # Ensure the page is fully loaded (wait for a known element, e.g., the schedule container)
        # TODO: UPDATE SELECTOR for the main schedule container or the 5:30 AM task element
        # page.wait_for_selector(".schedule-container")

        print("Starting automation loop...")

        # Base time from the template task
        current_time = datetime.strptime("05:30 AM", "%I:%M %p")

        for i in range(1, 47):
            # Increment time by 30 minutes for the new task
            current_time += timedelta(minutes=30)
            new_time_str = current_time.strftime("%I:%M %p")

            print(f"Iteration {i}/46: Creating schedule for {new_time_str}")

            # 2. Locate the existing 5:30 AM task and duplicate it
            # TODO: UPDATE SELECTOR for the specific 5:30 AM task element or its duplicate button
            # Example:
            # page.locator("text=5:30 AM").locator("..").locator("button[aria-label='Duplicate']").click()
            print("  - Clicking 'Duplicate' on the template task (Update selector!)")
            # page.click("button.duplicate-task-btn")
            page.wait_for_timeout(1000) # Wait for modal/form to appear

            # 3. Enter the new time
            # TODO: UPDATE SELECTOR for the time input field
            # Example:
            # page.fill("input[type='time']", current_time.strftime("%H:%M"))
            # OR if it's a text field:
            # page.fill("input[name='schedule_time']", new_time_str)
            print(f"  - Setting new time to {new_time_str} (Update selector!)")
            # page.fill("input.time-input", new_time_str)
            page.wait_for_timeout(500)

            # 4. Save/Submit the new schedule entry
            # TODO: UPDATE SELECTOR for the Save/Submit button
            print("  - Saving the new entry (Update selector!)")
            # page.click("button.save-btn")

            # 5. Verify the entry was saved successfully before continuing
            # Wait for a success toast, the modal to disappear, or the new time to appear in the list
            # TODO: UPDATE SELECTOR for the success indicator
            # Example:
            # page.wait_for_selector(".toast-success")
            # OR wait for the new time to appear:
            # page.wait_for_selector(f"text={new_time_str}")
            print("  - Waiting for save confirmation (Update selector!)")
            page.wait_for_timeout(1500) # Temporary fallback delay

        print("Successfully created 46 new schedule entries. Halting execution.")
        browser.close()

if __name__ == "__main__":
    main()
