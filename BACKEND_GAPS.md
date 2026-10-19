# Backend gaps

Things the Flutter client does that the API (`api-docs.md`, checked against
`main` 2026-10-19) has nowhere to keep. Each one works today, on the device
that did it, and silently does not follow the account anywhere else.

The point of this file is that none of these are client bugs to be fixed in
the client. They are fields and endpoints the backend does not have yet.

## 1. Folders (П-5)

**What the client does.** `features/chat_organizer` keeps two things in
shared preferences:

| What | Storage key | Shape |
|---|---|---|
| Folders | `chat_organizer.folders` | JSON array of folders, each a list of rules |
| Organizer settings | `chat_organizer.settings` | `{unarchive_on_new_message, folders_hidden}` |

**Why it is not on the server.** There is no folder resource in the API.

**What the user loses.** Reinstalling, switching phone, or signing in on the
web starts with the tab strip empty and the list unsorted. The note on the
folders screen (`organizerDeviceOnly`) is what says so.

**What the backend would need.**

- A folder resource: `GET/POST/PATCH/DELETE /chats/folders/` holding
  `{id, title, icon_key, match_mode, order, rules[]}` where a rule is
  `{type, ...}` with the five types the client already writes
  (`chat_type`, `unread`, `pinned`, `no_reply_from_me`, `member`). The client
  model (`data/models/folder_rule_model.dart`) is a flat record with a `type`
  discriminator and drops rule types it does not recognise, so the server can
  add types without breaking older builds.
- A per-user settings blob, or two booleans on the profile, for
  `unarchive_on_new_message` and `folders_hidden`.

**Client swap cost once it exists.** One file:
`data/datasources/chat_organizer_local_data_source.dart` gains a remote twin
behind the same interface, and
`presentation/providers/chat_organizer_providers.dart` points at it. The
repository, the use cases, the rules and every screen stay as they are — the
data source is already asynchronous for exactly this reason. That is the
trip pins and the archive already made.

**Unread counts per folder** are computed on the client from
`ChatDTO.unread_count` over the rows the list has loaded. With cursor
pagination that is "the pages fetched so far", not the whole account. A
server-side count per folder would be the honest number.

**The archive badge has the same shape of problem.** How much is in the
archive is now a second request (`GET /chats/?archived=true`), so the count
on the drawer is "what the first page of the archive holds", not the whole
archive. An `archived_count` / `archived_unread_count` on the list response
would let the drawer say the true number without fetching the set.

---

## 2. What the message search cannot reach (П-6)

The endpoint exists and the client uses it. Three limits are worth writing
down because they look like client bugs from the outside (api-docs §0.24,
§5.4.1):

- **Only `messages.content` is indexed.** Attachment file names, chat names
  and descriptions, and member names never match. A reader searching for a
  PDF by its name finds nothing, and nothing on screen explains why.
  `AttachmentDTO.file_name` in the index would fix the most common case.
- **No substring, no CJK.** The index is `simple` full-text: the last term
  matches by prefix and the rest exactly, so `юдже` does not find `бюджет`
  and a Japanese or Chinese query only matches where the text happens to be
  split the same way. A trigram index, or an ICU tokenizer for CJK, is the
  usual answer.
- **No ranking.** Results come back `id DESC`, newest first. For a query
  with one obvious answer deep in the history, that answer is on page four.
  `ts_rank` behind a `sort=relevance` would be enough.

The client compensates where it can: `MessageSearchTerms` repeats the
server's term rules so the snippet and the highlighting agree with what
matched, rather than looking for the query as one string and finding nothing.

---

## 3. Search history is local (П-6)

Recent queries (`search.recent_queries`) and recently opened chats
(`search.recent_chats`) are kept in shared preferences. Nothing in the API
stores either, and a list of things someone typed is not something to upload
on their behalf without asking. Worth a server-side home only if the product
wants search history to follow the account.

---

## 4. Drafts: synced, with two holes left on the server side

The client now writes drafts to the server and reads them back
(`presentation/providers/chat_drafts_provider.dart`): one write 1.5 s after
the typing stops, never more than the endpoint's 60 a minute (shared with
pins, mutes and the archive, ten slots always left for those), and the
device's copy kept as the offline cache. When the two copies disagree the
newer `draft_updated_at` wins (`domain/entities/chat_draft.dart`); the chat
list row shows the winner.

What the API still does not give:

- **`ChatDTO` has no `draft_updated_at`.** Only `ChatStateDTO` (the answer to
  a write) documents it. Without it on the list, a draft that changed on
  another device cannot be compared by time: the client falls back to "a
  local edit not yet written wins, otherwise the server's copy does". The
  model already reads `draft_updated_at` from `ChatDTO` if it appears —
  adding it to the list response is all it takes.
- **No realtime signal for a draft.** `chat_updated` carries chat settings,
  not the per-user state, so a draft typed on the laptop reaches the phone's
  list only on its next fetch (opening the app, pull to refresh). A
  `chat_state_updated` event to the user's own sessions with the
  `ChatStateDTO` would make it live.

---

## 5. Member rules still match on partial knowledge (П-5)

The "includes a person" folder rule can only look at what a chat row carries.
That is more than it was: `ChatDTO.peer` names the other person in every
direct chat, and `members_preview` carries up to three members of a group.
Beyond those three, a group's roster is only known to a screen that has
fetched it.

A folder like "chats with Ann" is therefore right about direct chats, right
about small groups, and blind to a large group Ann is quietly a member of.
A `member_ids` on the row, or server-side folder evaluation (gap 1), would
close it.

---

## 8. Invite links open nothing outside the app 🟡

The invite resource is on the API (api-docs §5.8): `POST /chats/{chat_id}/invites/`
mints a code with an optional expiry and use count, revoking it closes that
link alone, and `GET|POST /chats/invites/{code}/(join/)` preview and use it.
Public groups and channels also have an `@username` of their own
(`/chats/u/{username}/`, §5.9).

**What is still missing** is the web side. A link is only worth sending to
people who do not have the app if something answers it in a browser: a
landing page on the same origin that shows the chat's preview and deep links
into the app, plus the associated-domain / app-link records
(`apple-app-site-association`, `assetlinks.json`) so the installed app claims
the URL instead of the browser. Nothing on the server serves either today, so
an invite link followed from a browser is a 404.

---

## 11. Sharing a profile is passing a string around 🟡

Same cause as §8. The profile has a public address on the API now —
`GET /profiles/u/{username}/` answers without a token, case-insensitively,
with the photo hidden by the owner's privacy setting (api-docs §4.3) — but it
is JSON, not a page.

**What the client does.** `ProfileShareLink` composes
`https://<host>/profiles/<id>` from the configured origin and copies it to
the clipboard, with the name and handle above it when they are known. Inside
the app the link routes correctly; outside it, it is a 404. The profile's QR
code (long press on `@username`, П-11) encodes the same link.

**What the backend would need.** The landing page from §8, rendering a
public sliver of `/profiles/u/{username}/` and deep linking into the app —
`/u/{username}` is the natural shape. Since a username can now change
(api-docs §3.17), a link by handle breaks on rename; a link by id does not,
which is worth weighing when choosing what the QR code encodes.

---

## 12. An avatar upload is never confirmed or refused 🔴

`POST /profiles/avatar/upload_complete/` answers `200` and queues a
background task. That task decides the real MIME type (`python-magic`, by
content) and checks the 5 MB cap, and when it refuses the file it raises
`AVATAR_NOT_TYPE_IMAGE` or `AVATAR_SIZE` — into a worker, where no client
can see them (api-docs §2.5, §4.5). There is no status endpoint and no WS
event; chat attachments get `attachment_success` (§6.4), avatars get
nothing.

**What the client does.** Everything it can before uploading: the picture is
decoded, cropped and re-encoded on the device
(`presentation/utils/avatar_image.dart`), which both guarantees it really is
an image and keeps it inside the cap. After `upload_complete` it polls
`GET /profiles/my/` for about ten seconds
(`AvatarUploadController._awaitProcessing`) and calls the upload failed if
`avatars` never changes, offering the same picture back for a retry.

**What the user loses.** Up to ten seconds of waiting on a success, and a
failure message that cannot say *why* — "the server did not accept that
picture" is the whole of what the API makes knowable.

**What the backend would need.** Either an `avatar_success` / `avatar_failed`
WS event carrying the resulting `avatars` map or the error code, or a
`GET /profiles/avatar/status/{file_key}/` to poll deliberately instead of
watching a field for movement.

**Client swap cost once it exists.** `_awaitProcessing` is replaced by one
`await` on the event; the poll schedule, `AvatarPollSchedule`, and
`AvatarProcessingFailure`'s "we waited and nothing happened" meaning all go
away.

---

## 13. A mention is text, not an entity 🔴

`SendMessageRequest` (api-docs §5.4) carries `content` and nothing that
marks part of it as a person: no `entities`, no `mentions: user_id[]`. So an
`@mention` is the characters `@username` in the text, and the reader's
client finds them again by pattern and resolves them against the chat's
roster (`MessageLinkifier`, `MentionSyntax`).

**What the client does.** The composer offers members of groups and
channels when `@` is typed, filtered by username and display name, and
inserts `@username `. Only usernames that read back unambiguously are
offered — letters, digits, `.`, `_`, `-`, not ending in a dot.

**What the user loses.**

- A username set through `PUT /users/me/username/` follows strict rules
  (latin letters, digits and `_`, api-docs §3.17), but registration still
  accepts the legacy `^[a-zA-Z0-9 ,.'-]+$` (§3.2). A username with a space, a
  comma or an apostrophe has no end a pattern can find, so those people are
  not in the list and cannot be mentioned until they rename themselves.
- Nobody is notified of being mentioned: there is no server-side notion of
  it, so no push, no "you were mentioned" badge, no jump to the mention.
- A mention survives a rename only as the old text.

**What the backend would need.** Mention entities on the message —
`mentions: [{user_id, offset, length}]` in `SendMessageRequest` and
`MessageDTO` — validated against the roster, with a push to the mentioned
user and an `unread_mentions_count` on `ChatDTO`. The client would keep the
same composer and swap its pattern for the entity list when drawing.

---

## 14. "Send as file" for a photo may not be a file the server takes 🟡

The media preview offers "Send as file": every picked photo or video goes,
untouched and with its metadata, as `attachment_type: "file"` — one per
message, since `file` allows one (api-docs §5.5). But the documented MIME
list for `file` is documents only (pdf, zip, doc/docx, xls/xlsx, txt, csv);
`image/*` and `video/*` are not on it. Whether the server checks the
declared `attachment_type` against that list, or only infers the type from
the MIME when none is given, is not written down.

**What the client does.** Sends it anyway and shows whatever the server
answers in the attachment tray — a validation error there means the
backend does not accept photos as files.

**What the backend would need.** Either accept any allowed media MIME in the
`file` bucket (the usual meaning of "send uncompressed"), or say in
api-docs that it does not, and the item can go.

---

## 15. The address book: presence, deletions and other devices (contacts) 🟡

The contacts tab (`/contacts`, api-docs §4.7–4.13) is on the API now. Three
things it would show cannot be had from it.

- **Presence is per chat, not per person.** "online" ships only with a
  chat's member list (`?include_presence=true`, §5.3). A contact row says
  "online" only for someone this account has a direct chat with, and the
  handle otherwise — never "last seen", which the API does not have.
- **Deletions do not travel in a delta.** `GET /contacts/?updated_after=`
  returns changed rows only (§4.8); a contact removed on another device
  stays here until the next full read — on pull-to-refresh, on a new sign-in
  and at least every 7 days (`ContactSyncPolicy.fullEvery`).
- **Nothing pushes book changes.** A rename or a star set on another device
  shows up at the next sync, not live; the only contacts event on the socket
  is `contacts_import_completed`.

Import takes email only (§4.11, §0.19); the client reads addresses pasted
into a dialog and does not read the device's own address book.

**What the backend would need.** A presence read by user id (or presence in
`ContactProfileDTO`), tombstones in the delta (`deleted: [contact_id]` next
to `contacts`), and a `contacts_updated` socket event carrying the changed
`contact_id`s.

---

## 16. A block reaches direct chats, not groups (blocks) 🟡

Direct chats enforce the block (api-docs §4.13): a message, a forward or a
call between two people where either blocked the other is refused with
`403 USER_BLOCKED`, a new direct with them cannot be opened, the blocker
cannot be added to a group by the person they blocked, and the blocker's
photo and online status are hidden from them. A chat push carries
`{chat_id, message_id, sender_id}` in its payload
(`app/notifications/tasks/push_offline_recipients.py`), though api-docs §7.2
still calls the payload untyped.

**What is still a client-side rule.** Groups are deliberately untouched by
the block on the server, so the client keeps doing, on this device only:

- dropping a push whose `sender_id` is blocked
  (`ResolveNotificationDisplayUseCase(fromBlockedSender)`, also in the
  background isolate via `notification_blocked_senders`);
- leaving blocked people's direct chats out of the unread badges
  (`blockedDirectChatIdsProvider`) and out of "unarchive on new message".

**What the client cannot do.**

- `unread_count` is per chat: a blocked person writing in a group still
  raises that group's count.
- The in-app notification inbox and its badge (`GET /notifications/`,
  `/unread_count/`) are the server's numbers and include whatever the
  blocked person caused.
- Messages from a blocked person still appear in a group's feed.

**What the backend would need.** For groups: skip the push and the unread
increment for a sender the recipient blocked, and keep their activity out of
the notification inbox — or flag such messages so the client can collapse
them the way Telegram does. With that in place the client-side filter can
stay as a belt-and-braces check.

---

## 17. A person's profile: presence, last seen, shared media (П-11) 🟡

One profile page now serves every way of reaching a person (contacts, a
direct chat's header, a group's member list, a mention). Three things on it
are only as good as the API allows.

- **No "last seen".** Presence is a yes/no that ships only with a chat's
  member list (`?include_presence=true`, §5.3); there is no
  `last_seen_at` anywhere. The page says "online" when the direct chat's
  roster says so, "last seen recently" when it says offline, and nothing at
  all when there is no direct chat to ask — a stranger from a group has no
  status line. `ProfilePresence` in
  `features/profile/presentation/utils/profile_view.dart` is the rule.
- **Shared media only through a direct chat.** The Media / Files / Links /
  Voice tabs read `GET /chats/{chat_id}/media/` of the 1:1 chat (api-docs
  §5.12), so they exist only when that chat does. Media shared with the
  person in groups is not there: the index is per chat and has no "from this
  person" filter.
- **Mute is a setting of the chat.** "Mute" on the profile silences the
  direct chat (`PATCH /chats/{id}/state/`); without a chat it is greyed out
  — there is no per-person notification setting to write instead.

**What the backend would need.** A presence read by user id with a
`last_seen_at` — the same ask as §15; the `last_seen` privacy setting already
exists and would cover it — and a peer filter on the shared-media index (or
an index across all chats with that person).
