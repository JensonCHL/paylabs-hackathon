

Scope idea:
Financial reporting (Performance for the past month, most sold products, etc)
Financial advisor (for future expansion, or increase capex or take loan, or business planning)
Financial literacy (help umkm understand financial report through our chatbot)

Tech stack:
react : port 80
node
websocket or webhook:
n8n/langchain:
mcp
postgre (mongo if needed for transactions)
ai skills
docker
Alibaba llm endpoint
Alibaba ecs
Alibaba s3

arch:
Frontend | backend | agent | llm endpoint| db

containers:
Frontend : port 80
## Backend :port  5000
Agent : port 8000
Mcp server :port 5001
db(postgre or mongo): port 54321 or 554321



Main Database Schema Contains dummy data (2 months data):

## Main Database:
## Table 1:
merchants
(The UMKMs) We need to know who the business is to give them
personalized advice.
## ●
merchant_id
(UUID, Primary Key)
## ●
business_name
(String)
## ●
industry_type
(String - e.g., F&B, Retail, Services. Crucial for the AI advisor to
contextualize advice)
## ●
join_date
(Timestamp)
## ●
operating_city
(String)

## Table 2:
transactions
(The Core Logs) This is the main table the AI will query for
reporting.
## ●
transaction_id
(UUID, Primary Key)
## ●
merchant_id
(UUID, Foreign Key)
## ●
gross_amount
(Decimal)
## ●
net_amount
(Decimal - amount after Paylabs fees)
## ●
fee_deducted
(Decimal)
## ●
status
(String - SUCCESS, PENDING, FAILED, REFUNDED)
## ●
payment_method
(String - QRIS, VA_BCA, E_WALLET_OVO, etc.)
## ●
created_at
(Timestamp)
## Table 3:
transaction_items
(Optional but highly recommended) If you want the AI to
tell a UMKM "Your most sold product is X," the gateway needs to capture what was
actually sold. If Paylabs doesn't capture item-level data, you might just have a
product_category
or
description
column in the
transactions
table.
## ●
item_id
(UUID, Primary Key)
## ●
transaction_id
(UUID, Foreign Key)
## ●
item_name
(String)
## ●
category
(String)
## ●
quantity
(Integer)
## ●
unit_price
(Decimal)
- Chat History Database Schema To support Step 7 and ensure context is maintained
across sessions, the backend relies on a lightweight table to store the dialogue:
## Table:
chat_logs
## ●
log_id
(UUID, Primary Key)
## ●
chat_id
(UUID, Foreign Key linking to a specific session)
## ●
merchant_id
## (UUID)
## ●
role
(String: 'user' or 'assistant')
## ●
content
(Text: The actual message)
## ●
created_at
(Timestamp)
## 5. Table:
report_History
## ●
report_id
(UUID, Primary Key)
## ●
merchant_id
(UUID, Foreign Key)
## ●
generation_date
(Timestamp)

## ●
status
(String: PROCESSING, READY, FAILED)
## ●
total_revenue
(Numeric)
## ●
transaction_count
(Integer)
## ●
top_selling_item_name
(String)
## ●
top_selling_item_qty
(Integer)
## ●
financial_summary
(Text) - e.g., "Revenue is up 15% compared to last month."
## ●
pattern_analysis
(Text) - e.g., "Peak sales occur between 18:00 and 22:00."
## ●
strategic_advice
(Text) - e.g., "Consider running a promotion during your quiet
hours of 14:00 - 16:00."



Auto Reporting Schema & Flow (Page 1):


- User press “Generate Report” & monthly scheduled trigger in front end
Trigger: Backend receives the request and creates a new row with predefined variables in
staging tables in the database with a
status: "processing"
and a unique
task_id,
other column = null
. Waiting to be assign by the agent

- Backend receive input from user
- Backend pass parameter {merchandName, currentDate, etc} to Agent Listener

- Agent Listener receive parameter {merchandName, currentDate, etc} and begin MCP tools
and reasoning calls for analysis ex:
## - Get_transaction_history
- Analyze trends
- Analyze patterns
- Analyze market
## - Etc
- Agent will fill the staging table
The "Staging Table" Architecture
persistent "Staging Table" (e.g.,
report_generation_staging
## ).
Here is what that table should look like:
## Table:
report_generation_staging
## ●
report_id
(UUID, Primary Key)
## ●
merchant_id
(UUID, Foreign Key)
## ●
generation_date
(Timestamp)
## ●
status
(String: PROCESSING, READY, FAILED)
## ●
total_revenue
(Numeric)
## ●
transaction_count
(Integer)
## ●
top_selling_item_name
(String)
## ●
top_selling_item_qty
(Integer)
## ●
financial_summary
(Text) - e.g., "Revenue is up 15% compared to last month."
## ●
pattern_analysis
(Text) - e.g., "Peak sales occur between 18:00 and 22:00."
## ●
strategic_advice
(Text) - e.g., "Consider running a promotion during your quiet
hours of 14:00 - 16:00."

- The backend polls the table listens for
status
column. Once
status
column is "READY", it
pulls the perfectly structured row, maps it to the PDF template, and pushes it to your storage s3.
## 6. Copy
report_generation_staging
to
report_History

- Backend store the final document in s3
- will user see history & new report created.
- User can view & download and the backend will access from s3.

#Agent Architecture
Consist of 2 agents:
1.Agent1(Analyzer Agent) receive call trigger from backend receive parameter {merchandName,
currentDate, etc} from backend
- Task: Perform tool calls & analysis

- MCP Tools: tools1,tools2
- Agent2(Data Dump Agent)  receives all necessary information from agent 1 input all of the
predefined variable to Table:
report_generation_staging
based on information from
## Agent1
- Task: fill staging database
- MCP Tools: tools to fill database


Financial Literacy & Financial Advisor (Page 2)

Main structure = RAG but without embedding since we are working with numbers and small
amounts of data.
## User Interface & State Management
● Top Section: Visual Dashboard displaying transaction data (e.g., bar charts for revenue,
peak hours) filtered by the selected date range.
● Bottom Section: An interactive Chat UI acting as the Financial Co-pilot.
## Flow:
- Frontend user query input  query “What were my top selling items?”
- Backend receive from frontend and forward to agent.
- Webhook Payload Structure to Agents from backend:
## {
"Chat_id": "uuid-1234",
## "merchant_id": "uuid-merchant-888",
## "current_dashboard_view": {
## "start_date": "2026-02-01",
## "end_date": "2026-02-28"
## },
## "chat_history": [
{"role": "user", "content": "Why is my profit low this month?"},
{"role": "assistant", "content": "Your revenue is up, but your COGS (Cost of Goods Sold)
increased by 20%..."}
## ],
"user_message": "What were my top selling items?"
## }
- Agent process and agent thinking
- Agent returns output streaming response (per token response/ realtime response)
- Backend must parse the per token response/streaming response from the Agent and display
it to frontend
- Save Chat History into table

Persisting Chat History: Once the streaming completes, the backend concatenates the
streamed tokens into the final full response string. It then executes a database
## INSERT
to save
both the
user_message
and the complete
assistant_response
into the PostgreSQL
chat_history
table using the associated
## Chat_id
## .
## 8. Donee



(Extension kalo sempet) Suspicious Transaction Detection Alert
(Extension kalo sempet) Daily Transaction summary