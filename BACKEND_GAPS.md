# Backend gaps

Things the Flutter client does that the API (`api-docs.md`, checked against
`main` 2026-09-15) has nowhere to keep. Each one works today, on the device
that did it, and silently does not follow the account anywhere else.

The point of this file is that none of these are client bugs to be fixed in
the client. They are fields and endpoints the backend does not have yet.

## Closed since the last pass

The API grew the per-user chat state this file used to ask for, and the
client now uses it. Kept here as a record of what moved, not as work:

| What | Where it lives now |
|---|---|
| Pinned chats, and the five-pin limit | `ChatDTO.is_pinned` / `pinned_at`, `PATCH /chats/{id}/state/`, `400 PINNED_CHATS_LIMIT_EXCEEDED` |
| The archive | `ChatDTO.is_archived`, and `GET /chats/?archived=true` as a set of its own |
| Silenced notifications | `ChatDTO.notifications_muted_until` / `is_muted_by_me` |
| Who to draw on a row | `ChatDTO.peer` for direct chats, `members_preview` for groups |
| Searching messages | `GET /chats/messages/search/`, cursor over message ids |
| Searching people in one field | `GET /profiles/?q=`, matching username OR display name |
| A profile knowing its own handle | `ProfileDTO.username` — non-null, on `GET /profiles/{id}/` and on the list |
| Drafts that follow the account | `ChatDTO.draft`, `PATCH /chats/{id}/state/ {draft}` → `ChatStateDTO.draft_updated_at` (see §4 for what is still missing) |

On the client: `features/chat/presentation/providers/chat_state_actions.dart`
writes all three through one endpoint and moves the row while the request is
in flight; `features/chat_organizer` kept folders and gave up everything
else; `chat_flags.pinned`, `chat_flags.archived` and `chat_flags.muted` are
no longer read or written, and stale copies in shared preferences are simply
ignored.

⚠️ Nothing migrates what those keys held. A device that had pinned five chats
before this version starts from whatever the server says, which for an
account that has never pinned anything is nothing.

The message search kept its local half as an offline fallback rather than
deleting it: `OfflineFallbackMessageSearchRepository` asks the server, and
only when that request could not be made at all — no network, a timeout —
searches what this device has loaded and says so on screen. A rate limit or
a validation error is shown, not papered over.

---

## 1. Folders (П-5)

**What the client does.** `features/chat_organizer` keeps two things in
shared preferences:

| What | Storage key | Shape |
|---|---|---|
| Folders | `chat_organizer.folders` | JSON array of folders, each a list of rules |
| Organizer settings | `chat_organizer.settings` | `{unarchive_on_new_message, folders_hidden}` |

**Why it is not on the server.** There is no folder resource in the API.
Pins, the archive and the notification mute used to be in this list and are
not any more — see "Closed" above.

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

## 6. A chat has no avatar anyone can set 🔴

`ChatDTO.avatar_s3_key` and `ChatDetailDTO.avatar_s3_key` are readable and
nothing else. There is no chat equivalent of the profile avatar flow from
api-docs §4.5:

| What exists for a profile | What exists for a chat |
|---|---|
| `POST /profiles/{id}/avatar/presign/` → presigned PUT | — |
| `avatar_s3_key` written by the confirm step | `avatar_s3_key` is read-only |
| `avatars` matrix of sizes/formats on the DTO | not present |
| `avatar_url`, presigned, 300 s TTL | not present |

`UpdateChatRequest` (api-docs §5.2) takes `name`, `description`, `is_public`,
`admin_only`, `slow_mode_seconds` and `permissions` — no avatar field — so
even a key uploaded some other way could not be attached to the chat.

**What the client does.** Nothing: the chat profile screen has no way to
change a picture, because there is no button that could work. A group draws
the mosaic of its members' faces (`members_preview`, or the roster when the
screen has one) and falls back to its initial on its own colour;
`avatar_s3_key` is carried through the model and never resolved, since there
is no endpoint that turns a key into a URL either.

**What it needs.** The §4.5 pair, scoped to a chat and gated on
`chat:update`: a presign endpoint, a confirm that writes `avatar_s3_key`, and
a presigned `avatar_url` on `ChatDTO` / `ChatDetailDTO` with the same 300 s
TTL as every other avatar — cached by `s3_key`, never by the URL.

---

## 7. No shared-media index for a chat 🔴

There is no `GET /chats/{chat_id}/media/`, no `?has_attachments=` filter on
`GET /chats/{chat_id}/messages/`, and no attachment collection of any kind.
Attachments exist only inside the message that carried them (api-docs §5.4,
§5.5), and the only way to enumerate them is to walk the message history.

**What the client does.** The chat profile's Media / Files / Links / Voice
tabs are built on the device, from two overlapping views of the same
history: the window the chat screen has loaded, and the 200 messages the
local cache keeps per chat
(`presentation/utils/chat_shared_content.dart`,
`presentation/providers/chat_profile_provider.dart`). Links are not a server
concept at all — they are found by running message text through the same
parser the bubbles use.

**What the user loses.** The tabs are as deep as this device's history and no
deeper. A photo sent last year is not in them until someone scrolls back far
enough in the chat for it to be, and a fresh install starts with all four
tabs empty. Every tab says so in a line under the list
(`sharedContentLocalOnly`), rather than passing off a partial answer as a
complete one.

**What it needs.** Either a media endpoint with its own cursor
(`GET /chats/{chat_id}/attachments/?type=image|video|file|voice`) or a
`has_attachments` / `attachment_type` filter on the message list. Either one
also removes the reason `MediaViewerScreen` has to fall back to fetching a
single message when the viewer is opened outside the loaded window.

---

## 8. Public chats have no invite link of their own 🔴

`POST /chats/{chat_id}/join/` lets any signed-in user into a chat with
`is_public: true` (api-docs §5.2), but nothing mints a way to hand that chat
to somebody: no invite token, no public slug or `@handle` for a chat, no
revocable link, no landing page. `is_public` is the whole of the access
model.

**What the client does.** Composes `https://<origin>/chats/<chat_id>` from
the configured server origin and the chat id
(`presentation/utils/chat_invite_link.dart`), shows it on the profile of a
public chat, and copies it to the clipboard.

**What the user loses.** The link only means something to someone who
already has ChatiX and is signed in — there is no web page behind it, and
following it from a browser does nothing. It also cannot be revoked,
expired, or limited to a number of uses, because it is not a token: it is
the chat's id, which never changes. Turning `is_public` off is the only way
to close the door, and it closes it for every link at once.

**What it needs.** An invite resource — `POST /chats/{chat_id}/invites/`
returning a token with an optional expiry and use count, `DELETE` to revoke,
and a join-by-token endpoint — plus, for links to be worth sending to people
who do not have the app, a web landing page on the same origin and
associated-domain / app-link records so the app claims the URL.

---

## 9. `member:mute` is a permission with nothing behind it 🔴

The chat role matrix gives `member:mute` to owner and admin (api-docs §8.1),
`MemberChatDTO` and `MemberDetailDTO` both report `is_muted`, and the
composer already reads it: a muted member sees `composerMuted` instead of a
text field. What is missing is the endpoint that sets it. The members router
has exactly four writes (api-docs §5.3):

| What | Endpoint |
|---|---|
| Add | `POST /chats/{chat_id}/members/` |
| Change role | `PATCH /chats/{chat_id}/members/{user_id}/role/` |
| Ban / unban | `PATCH /chats/{chat_id}/members/{user_id}/ban/` |
| Kick | `DELETE /chats/{chat_id}/members/{user_id}/` |

There is no `.../mute/` among them. `POST /chats/{chat_id}/calls/participants/{user_id}/mute/`
is a different thing entirely — it silences a microphone in a LiveKit room
(`call:mute_member`), not a member's right to post.

**What the client does.** Nothing, deliberately. `ChatMemberAction`
(`presentation/utils/chat_member_actions.dart`) has no `mute` case, so the
member list's action sheet never offers one — a button that cannot send a
request is worse than no button. The state is still shown: a muted member
wears a `Muted` badge in the list, and the permission itself is honoured
everywhere it is read.

**What the user loses.** A moderator can only ban or remove someone. There is
no middle step between "may post" and "is out of the chat", which is the
usual answer to one bad afternoon.

**What the backend would need.** `PATCH /chats/{chat_id}/members/{user_id}/mute/`
shaped like the ban endpoint — `{reason?: string, muted_to?: datetime}` with
the same three readings of the date (null forever, future temporary, past
lifts it) — plus a `member_muted` WS event carrying
`{target_user_id, requester_id, mute}` so the other clients and the
composer's `is_muted` update without a refetch.

**Client swap cost once it exists.** A `MuteMemberUseCase` beside
`BanMemberUseCase`, one method on `ChatMembersController`, and two entries in
`ChatMemberAction` (`mute`, `unmute`) — the permission check
(`hasChatPermission(chat, me, ChatPermissions.memberMute)`) and the badge are
already written.

---

## 11. Sharing a profile is passing a string around 🔴

Same shape as the chat invite link in §8, and the same cause. There is no
public identity for a profile: no slug, no shareable URL, and
`GET /profiles/{id}/` needs a token (§4.2 closed the list too). So there is
nothing to hand somebody that opens anywhere.

**What the client does.** `ProfileShareLink` composes
`https://<host>/profiles/<id>` from the configured origin and copies it to
the clipboard, with the name and handle above it when they are known. Inside
the app the link routes correctly; outside it, it is a 404.

**What the user loses.** "Share profile" reaches people who already have
ChatiX and are signed in. Sending one to anybody else does nothing. The
same holds for the profile's QR code (long press on `@username`, П-11): it
encodes this link, so a phone camera opens a 404 rather than the person.

**What the backend would need.** The same landing-page work §8 asks for — a
web page on the origin that renders a public sliver of a profile and deep
links into the app. The handle to address it by now exists
(`ProfileDTO.username`), so `/u/{username}` is available as a shape; what is
missing is something that serves it.

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

- `username` may be `^[a-zA-Z0-9 ,.'-]+$` (api-docs §3.2). A username with a
  space, a comma or an apostrophe has no end a pattern can find, so those
  people are not in the list and cannot be mentioned at all.
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

## 16. A block is a list, not a rule (blocks) 🔴

`POST`/`DELETE /contacts/{user_id}/block/` and `GET /contacts/blocked/`
exist (api-docs §4.13), but the same section says the chats do not check
them yet ("этап 2"): a blocked person's message is accepted, delivered over
the socket, counted in `unread_count` and pushed like anyone else's.

**What the client does instead — all of it on this device only:**

- **Notifications.** `PushNotificationPresenter` drops a push whose sender is
  blocked (`ResolveNotificationDisplayUseCase(fromBlockedSender)`), both in
  the running app and in the background isolate, which reads a copy of the
  list from shared preferences (`notification_blocked_senders`, written by
  `blockedSendersSnapshotProvider`).
- **The unread badge.** The chats tab, the folder tabs and the archive
  header leave out direct chats with blocked people
  (`blockedDirectChatIdsProvider`); their row keeps its count in the quiet
  fill with a block mark.
- **The composer.** A direct chat with a blocked person has a bar instead
  ("You blocked this user · Unblock").
- **The archive.** A blocked person writing does not pull their chat back
  out of the archive.

**What the client cannot do.**

- A push payload is untyped (api-docs §7.2). A blocked person is recognised
  by `sender_id` (or `author_id`, `from_user_id`) when the payload has one,
  and otherwise only in their direct chat, by its id. A group message from a
  blocked person in a push without a sender id is shown.
- `unread_count` is per chat. A blocked person writing in a group still
  raises that group's count.
- The in-app notification inbox and its badge (`GET /notifications/`,
  `/unread_count/`) are the server's numbers and include whatever the
  blocked person caused.
- Messages from a blocked person still appear in the feed when the chat is
  opened; the confirmation dialog and the block list both say so.

**What the backend would need.** "Этап 2" itself: refuse `POST
/chats/{id}/messages/` from a sender the recipient blocked in a direct chat
(and say so with a code), skip the push and the unread increment for a
blocked sender in groups, and either a `sender_id` in every chat push
payload or a typed payload. With that in place the client-side filter can
stay as a belt-and-braces check; nothing else changes.

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
- **Shared media only through a direct chat, and only what is cached.**
  The Media / Files / Links / Voice tabs appear when a 1:1 chat exists and
  show what this device holds of it (§7 above: no shared-media index).
  Media shared with the person in groups is not there.
- **Mute is a setting of the chat.** "Mute" on the profile silences the
  direct chat (`PATCH /chats/{id}/state/`); without a chat it is greyed out
  — there is no per-person notification setting to write instead.

**What the backend would need.** A presence read by user id with a
`last_seen_at` (rounded, with a privacy setting, if wanted) — the same ask as
§15 — and the shared-media index from §7, ideally filterable by peer.
