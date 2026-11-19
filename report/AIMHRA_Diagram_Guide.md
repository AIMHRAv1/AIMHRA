# AIMHRA — Diagram Notes

These notes give the main parts and connections to include in five separate
diagrams. Use the names and arrows below as a starting point, then arrange the
shapes neatly on the page.

## 1. Use-case diagram

Draw a large boundary labeled **AIMHRA Maternal Health System**. Put the
**Healthcare Worker** and **Administrator** outside the boundary.

### Healthcare Worker connects to

- Sign in
- Manage patient records
- Record a maternal health assessment
- View risk results and assessment history
- Review alerts
- Generate care advisory
- Generate patient report

### Administrator connects to

- Sign in
- Manage healthcare-worker accounts
- Manage medical knowledge documents
- Manage and view prediction models
- View system activity
- View patient risk summaries

Add **Patient** as a note or data subject, not an actor: patients' information
is entered by healthcare workers; patients do not log in. If desired, draw
**Local AI Assistant** as a supporting external service connected to “Generate
care advisory,” not as a person using the system.

## 2. System architecture diagram

Draw the system in layers, from users at the top to saved data at the bottom:

```text
Healthcare Worker                 Administrator
         \                         /
             AIMHRA Web Screens
                     |
                Backend API
          ___________|____________
         |           |            |
 Patient/Assessment  Risk &      Advisory,
     Services        Alerts      Chat & Reports
         |            |            |
         |      Trained Model      Knowledge Base
         |      + Risk Rules            |
         |______________________________|
                     |
              Database + Files

             Advisory / Chat
                    |
          Local AI (optional)
```

In the diagram, explain the connections simply:

- Users work through the web screens; the backend receives their requests.
- Patient and assessment information is saved in the database.
- The risk service uses a trained model and a separate set of clinical rules.
- Advisories and chat use the knowledge base; an optional local AI helps write
  responses.
- Uploaded documents, photos, and generated reports are kept as files.

## 3. DFD Level 0 — Context diagram

Draw one process in the center: **AIMHRA System**. Around it, draw
**Healthcare Worker**, **Administrator**, and **Local AI (optional)**.

Label the arrows:

- **Healthcare Worker → AIMHRA:** patient information, assessment measurements,
  symptoms, notes, and requests for advice or reports.
- **AIMHRA → Healthcare Worker:** risk result, explanation, alerts, assessment
  history, care advice, and reports.
- **Administrator → AIMHRA:** staff changes, knowledge documents, and model
  management requests.
- **AIMHRA → Administrator:** staff and model information, system activity,
  and patient risk summaries.
- **AIMHRA → Local AI:** a question or advisory request with relevant
  information and knowledge excerpts.
- **Local AI → AIMHRA:** a generated response.

Keep the whole application as one process in Level 0; do not show internal
database tables or backend modules here.

## 4. DFD Level 1

Replace the single AIMHRA process with these main processes:

1. **Manage users and access**
2. **Manage patient records**
3. **Record assessment**
4. **Calculate risk and manage alerts**
5. **Generate care advisory**
6. **Create and download report**
7. **Manage knowledge and models**

Add these data stores:

- **User Records**
- **Patient Records**
- **Assessment and Risk Results**
- **Medical Knowledge Base**
- **Reports and Activity Records**

Connect the flows like this:

- The healthcare worker sends patient details to **Manage patient records**;
  that process saves and reads **Patient Records**.
- The worker submits measurements, symptoms, and notes to **Record
  assessment**; it saves the assessment in **Assessment and Risk Results**.
- **Calculate risk and manage alerts** reads the assessment, uses the trained
  model and clinical rules, saves the result/alerts, and returns them to the
  worker.
- **Generate care advisory** reads the assessment and relevant patient
  information, looks up supporting material in the **Medical Knowledge Base**,
  and returns advice to the worker. It may use **Local AI** to compose the
  response.
- **Create and download report** reads the patient and risk result and saves a
  report in **Reports and Activity Records**.
- The administrator sends staff, knowledge, and model updates to **Manage
  knowledge and models**; the process updates the related stores.
- **Manage users and access** checks the user's role before allowing
  administrator or healthcare-worker actions.

## 5. Block diagram — Assessment and advice flow

Show this sequence from left to right or top to bottom:

```text
Healthcare worker enters patient and assessment information
                              |
                              v
                   Validate the information
                              |
                              v
                   Save the assessment
                              |
                              v
          +-------------------+-------------------+
          |                                       |
          v                                       v
  Trained risk model                       Clinical rule checks
          |                                       |
          +-------------------+-------------------+
                              |
                              v
                Risk result and any alerts
                              |
                 +------------+-----------+
                 |                        |
                 v                        v
        Show result/history       Create care advisory
                                          |
                           Patient information + knowledge base
                                          |
                                 Optional local AI
```

The risk model and clinical rule checks are separate inputs to the result.
The advisory uses patient and assessment context together with the medical
knowledge base; local AI is optional.
