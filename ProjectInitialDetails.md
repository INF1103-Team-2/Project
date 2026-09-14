INF1103 Project
Domain: Healthcare 

Topic: Error logging 

Problem Statement:
There can be many error logs that a company needs to process, but the issue is how do we process all of the error logs and make it so that we can generate a report that shows us all of the different issues?
Target Users: 
Hospital Staffs; Engineers; Operators
User Inputs:
Error logs from the machines
Use of AI
Send out alerts; Check up on the machine for any anomalies; Status of the machines; 

Solution:

IO Manager: -Zoey
- User to input the raw data (error logs [.file format]) into the application (front end).

AI Manager: - Jing Jie, Owen
- Gather the raw data from the IO Manager and sort out error logs and push the sorted data format to the Logic Manager.

Logic Manager: - Jia Yi, Naim
- Using the sorted data and sending out the different errors to the Telegram API.
- Telegram API (bot) will send the message to the engineer to fix the issue.
2 Case Scenarios:
A. URGENT ERROR: Immediately send out the message to 
the engineer to resolve.
B. > URGENT ERROR: Will wait a few days [to be specified] and will send out the message after 7am.

Data Manager: - Subin
- JSON file to store everything