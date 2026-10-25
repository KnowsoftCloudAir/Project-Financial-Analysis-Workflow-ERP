# Social stream starter CSV + login code clarification

## CSV file
`churchgate_social_stream_links.csv` — your full library arranged for upload.

Columns: **platform, title, source_url (Public URL), category, description (Note), is_active, sort_order**

Categories used:
- **movies** — faith films (Noah, Passion, Pilgrim's Progress, …)
- **news** — CNN, BBC, Sky, Al Jazeera, Channels, …
- **tv** — general TV / regional channels
- **ministration** — sermons, teachers, church live services
- **games** — sports (NBA, F1, FIFA, WWE, …)

## Upload after deploy
1. Admin → Social Stream  
2. Upload this CSV  
3. Tick **Replace all** if the list should match the file exactly  

## Login codes (confirmed behaviour)
| Situation | Code / link required? |
|-----------|------------------------|
| **Every normal login** | **No** — only email + password |
| **New registration** | **Yes, once** — confirmation link in email |
| **Password reset** | **Yes, only when resetting** — code + form link |

Users do **not** receive a login code every time they sign in.
