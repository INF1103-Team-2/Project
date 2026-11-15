INF1103 Project

GitHub URL: https://github.com/INF1103-Team-2/Project.git

Domain: Healthcare 

Topic: Error logging 

Problem Statement:
There can be many error logs that a company needs to process, but the issue is how do we process all of the error logs and make it so that we can generate a report that shows us all of the different issues?

Target Users: 
Hospital Staff, Engineers, Operators

User Inputs:
Error logs from the machines

Use of AI:
Monitor machine status for anomalies, send alerts when issues are detected, and provide regular status updates.

Business Rule:
To maintain operational integrity and avoid alert fatigue, the Logic Manager applies the following strict business rules to all AI-categorized outputs:

A. Notification & Escalation Rules (Decision Logic)
Rule 1 (Immediate Alert): IF the AI classifies an error severity as URGENT, THEN the Logic Manager must immediately dispatch a Telegram notification to the on-duty engineer, regardless of the time of day.
Rule 2 (Non-Urgent Batching): IF the AI classifies an error severity as NON-URGENT, THEN the system must store the record in the Data Manager and queue the notification until the standard window opens. (Daily after 07:00 AM).
Rule 3 (Suppression of Repeated Errors): IF a machine generates the exact same error_code multiple times within a 10-minute window, THEN the system will bundle them into a single consolidated notification to prevent spamming the engineering team.

B. Data Validation Rules
Rule 4 (Invalid File Rejection): The IO Manager must reject any uploaded file that does not contain the mandatory schema parameters (`machine_id`, timestamp, and `error_code`). Invalid files will trigger a front-end error message: *"Invalid log format. Upload aborted."*
Rule 5 (AI Confidence Threshold): IF the AI Analysis Manager processes a log but returns a confidence score below 75% for its classification, THEN the error status must default to PENDING REVIEW and be flagged for manual review by the Operator, bypassing automated Telegram dispatch.

Solution:
IO Manager: Zoey
- User to input the raw data (error logs [.file format]) into the application (front end).

AI Manager: Jing Jie, Owen
- Gather the raw data from the IO Manager and sort out error logs and push the sorted data format to the Logic Manager.

Logic Manager: Jia Yi, Naim
- Using the sorted data and sending out the different errors to the Telegram API.
- Telegram API (bot) will send the message to the engineer to fix the issue.
    2 Case Scenarios:
    A. URGENT ERROR: Immediately send out the message to 
    the engineer to resolve.
    B. > URGENT ERROR: Will wait a few days [to be specified] and will send out the message after 7am.

Data Manager: Subin
- JSON file to store everything
