# AutoLedger — User Guide

This guide is for the people who **use** AutoLedger day to day: logging fuel,
keeping an eye on costs and not missing the MOT. You don't need to know
anything about how it's built or installed. If you're the person who sets it up
and keeps it running, see the [README](README.md) instead.

---

## Contents

1. [What AutoLedger does](#what-autoledger-does)
2. [Opening AutoLedger and signing in](#opening-autoledger-and-signing-in)
3. [Finding your way around](#finding-your-way-around)
4. [How do I…?](#how-do-i)
   - [Add my car](#add-my-car)
   - [Switch between cars](#switch-between-cars)
   - [Log a fuel fill-up](#log-a-fuel-fill-up)
   - [Log another cost (insurance, a service, tax…)](#log-another-cost)
   - [Fix or delete something I entered](#fix-or-delete-something-i-entered)
   - [Find an old entry](#find-an-old-entry)
   - [Get reminded about the MOT, service, tax or insurance](#get-reminded-about-the-mot-service-tax-or-insurance)
   - [Get reminders by email or on Home Assistant](#get-reminders-by-email-or-on-home-assistant)
   - [See what I'm spending and how economical the car is](#see-what-im-spending-and-how-economical-the-car-is)
   - [Make a backup of everything](#make-a-backup-of-everything)
   - [Bring in my history from LubeLogger](#bring-in-my-history-from-lubelogger)
   - [Change the currency, categories, time zone or reminder time](#change-the-currency-categories-time-zone-or-reminder-time)
   - [Remove a car I've sold](#remove-a-car-ive-sold)
5. [Understanding the numbers](#understanding-the-numbers)
6. [Something went wrong](#something-went-wrong)
7. [Glossary](#glossary)

---

## What AutoLedger does

AutoLedger is a private logbook for what your cars cost to run. You record
each fill-up and each bill (insurance, servicing, road tax and so on), and it
tells you:

- how much you're spending, month by month and year by year;
- how many **miles per gallon** you're getting, and whether that's changing;
- when the **MOT, service, road tax or insurance** is coming up, and it can
  warn you by email or on your Home Assistant dashboard.

Everything stays on your own home server. Nothing is sent to an outside company
unless you turn on email reminders.

---

## Opening AutoLedger and signing in

Open the web address you were given in your usual web browser (on a computer,
tablet or phone). It will look something like `http://yourserver:5050`.

**The very first time**, AutoLedger asks you to **create an account**. Pick a
username and a password of at least 8 characters, type the password twice, and
press **Create account & sign in**. There is only one account, so everyone in
the household uses the same sign-in.

**After that**, you'll see a normal **Sign in** screen whenever you open it
in a new browser or after signing out.

**To sign out**, press **Sign out** at the bottom of the menu on the left.

> **Keep the password somewhere safe**, such as a password manager.
> AutoLedger can't email you a reset link. If it's forgotten, the person who
> looks after the server can reset the sign-in without losing any of your
> records (see [Something went wrong](#something-went-wrong)).

---

## Finding your way around

The menu down the left-hand side has seven pages:

| Page | What it's for |
|---|---|
| **Dashboard** | The home page. Add a new entry, see the latest ones, see the current mileage and any reminders that are due. |
| **All Entries** | The full history for the selected car, with search and sorting. |
| **Reports** | Charts of spending and fuel economy. |
| **Reminders** | MOT, service, tax and insurance reminders. |
| **Import / Export** | Make a backup, restore one, or bring in records from LubeLogger. |
| **Vehicles** | Add, edit or remove cars. |
| **Settings** | Currency, cost categories, time zone, reminder time and notifications. |

At the **top of the menu** is the **Active vehicle** box. Everything you see
and add applies to the car shown there. A number next to **Reminders** means
some reminders are due or overdue.

AutoLedger follows your device's **light or dark** appearance automatically.
Dates are shown day first (DD/MM/YYYY).

---

## How do I…?

### Add my car

1. Go to **Vehicles**.
2. Fill in the form. Only a **Nickname** (such as "Daily Driver") is really
   needed; make, model, year, colour, registration and notes are optional but
   make things easier to tell apart.
3. Press **Add Vehicle**.

The first car you add becomes the active vehicle.

### Switch between cars

Click the **Active vehicle** box at the top of the left-hand menu and choose
the car, or press **Set active** on the car's card on the **Vehicles** page.
Every page (entries, reports, reminders) now shows that car.

### Log a fuel fill-up

1. Make sure the right car is selected (top of the menu).
2. On the **Dashboard**, find **Add New Entry**.
3. Set **Category** to **Fuel**. Extra boxes appear for fuel.
4. Enter:
   - **Amount**: what you paid in total;
   - **Date**: today is filled in for you;
   - **Litres**: from the pump or receipt;
   - **Odometer (miles)**: the car's mileage reading when you filled up;
   - **Price per litre**: leave this on **auto** and it's worked out for you.
5. Tick **Full tank** if you filled right up to the click.
6. Optionally add a **Note** ("BP, motorway"), then press **Add**.

> **Why "Full tank" matters:** miles per gallon can only be worked out between
> two *full* fills, because only then do you know exactly how much fuel the
> car used. A partial top-up still counts towards spending, and its litres are
> included in the next full-to-full calculation. Just don't tick the box for it.

### Log another cost

Same as fuel, but pick the matching **Category**: *Insurance*, *Servicing &
Repairs*, *Tax & Registration*, or any category you've added yourself. Enter
the **Amount**, the **Date** and an optional **Note**, then press **Add**. The
fuel-only boxes don't appear.

### Fix or delete something I entered

Every entry in **Recent Entries** (Dashboard) and **All Entries** has two
buttons at the end of its row:

- **Edit** opens the entry. Change what you need and press **Save changes**.
- **✕** deletes it. You'll be asked to confirm, and it can't be undone (unless
  you restore a backup).

### Find an old entry

Go to **All Entries**. You can:

- type in **Search notes…** to find entries whose note or category contains
  what you type (for example "BP" or "insurance");
- sort by date, amount or category using the sort options at the top.

Fuel rows have a small expand button that shows the detail for that fill-up:
MPG for that tank, litres, odometer reading and cost per mile.

### Get reminded about the MOT, service, tax or insurance

1. Go to **Reminders** and make sure the right car is selected.
2. Choose the **Type**: MOT, Service, Tax, Insurance, or **Custom…** (then type
   a label such as "Cambelt change").
3. Say when it's due. You can use either or both:
   - a **Due date**; and/or
   - a **Due mileage** (for example 60,000).

   If you give both, whichever comes first counts.
4. **Warn me**: how many days before the date, and/or how many miles before
   the mileage, you'd like the warning to start.
5. **Repeat every** (optional): for example every 12 months, or every 10,000
   miles. When you've done the job (the MOT is passed, the service is booked
   in), press **✓ Mark done** on the reminder and it moves on to the next due
   date or mileage. It doesn't move on by itself, so an MOT you haven't marked
   done keeps showing as overdue.
6. Tick **Send notifications when due** if you want an email or Home Assistant
   alert as well as the on-screen warning.
7. Press **Add Reminder**.

Due and overdue reminders show as a banner on the **Dashboard**. AutoLedger
checks once a day at the time set in **Settings**. Press **↻ Check now** on the
Reminders page to check straight away.

> AutoLedger knows the car's current mileage from the **odometer reading on
> your latest fuel entry**. If you haven't logged fuel for a while, mileage
> reminders will be based on that older reading.

### Get reminders by email or on Home Assistant

This is usually set up once by whoever looks after the server. If it's up to
you, go to **Settings → Notifications**.

**Email:** fill in the mail server details (there's a **Setup help** link with
exact values for Resend and Gmail), the **From address** and **Send to**, then
press **Save email settings**. Press **Send test email** to check it works: you
should receive a test message within a minute. For Gmail you need a Google
**App Password**, not your normal Gmail password.

**Home Assistant:** enter your Home Assistant web address and a **long-lived
access token** (created in Home Assistant under your profile → Security), then
**Save Home Assistant settings** and **Send test**. Optionally name a notify
service (such as your phone) to get a push notification too.

Saved passwords and tokens are stored scrambled and are never shown again. To
keep an existing one, leave its box blank when you save.

### See what I'm spending and how economical the car is

Go to **Reports** and choose a **Period** (3, 6 or 12 months, or all time). You
get ten charts and tables for the selected car:

| Report | What it tells you |
|---|---|
| Monthly Spend | Total cost each month, split by category |
| Spend by Category | What share of the money goes on fuel, insurance, etc. |
| Cumulative Spend | The running total over the period |
| Fuel Efficiency: MPG | Miles per gallon between full-tank fills |
| Fuel Efficiency: km/L | The same, in kilometres per litre |
| Price per Litre Trend | What you paid per litre at each fill-up |
| Cost per Mile | Total running cost divided by miles driven, per month |
| Fill-up Interval | Days between fill-ups, showing how much the car is used |
| Fuel vs Other Costs | When the big non-fuel bills landed |
| Annual Breakdown | A year-by-year table, handy for budgeting |

### Make a backup of everything

Go to **Import / Export** and press **Download backup…** under **Export
AutoLedger JSON**. A file downloads containing **every car and every entry**.
Keep it somewhere safe, such as cloud storage.

> The backup file does **not** include your **reminders**, **settings** or
> notification details. After restoring onto a fresh AutoLedger you'd need to
> set those up again. For a complete copy of everything, ask whoever manages the
> server to back up AutoLedger's data folder, which they do separately.

**To restore** from that file, use **Choose file…** under **Import AutoLedger
JSON**. Entries that already exist are skipped, so restoring twice won't create
duplicates.

### Bring in my history from LubeLogger

1. In LubeLogger, export the fuel log for **one** car as a CSV file.
2. In AutoLedger, add that car on **Vehicles** (if you haven't already) and
   select it as the **Active vehicle**.
3. Go to **Import / Export** → **Import LubeLogger CSV** → **Choose CSV…** and
   pick the file.

Repeat for each car. If you import the same car again after changing things in
LubeLogger, use **Re-import CSV…** instead. It replaces that car's previously
imported LubeLogger records rather than adding them twice. Anything you entered
directly in AutoLedger is left alone.

### Change the currency, categories, time zone or reminder time

Go to **Settings**:

- **Currency**: pick a common one or type your own symbol and press **Use this**.
- **Cost Categories**: add your own (for example "Parking" or "Car wash")
  with **+ Add**, or remove ones you don't use.
- **Efficiency Bounds**: see [Understanding the numbers](#understanding-the-numbers).
  Most people never need to touch these.
- **Reminder Schedule**:
  - **Daily check time**: when AutoLedger checks reminders and sends alerts.
  - **Time zone**: where you are (for example *Europe/London*). It decides when
    "today" starts, which date new entries default to, and when the daily check
    runs. Change it only if you live somewhere else.

Press **Save settings** at the bottom. A "✓ Settings saved" message confirms it.

### Remove a car I've sold

Go to **Vehicles** and press **Delete** on the car's card. You'll be asked:

- **Delete vehicle only**: removes the car. Its entries are kept in the data
  (and in backups) but **no longer appear anywhere in the app**, because every
  page shows one car at a time.
- **Delete vehicle + all costs**: removes the car and everything logged
  against it.

Neither can be undone, so **make a backup first**.

**If you still want to see its history** (for tax, or to compare costs), don't
delete it. Press **Edit** on the car and add a note such as "Sold March 2026"
instead.

---

## Understanding the numbers

- **MPG** uses **UK (imperial) gallons**. It is calculated from one full-tank
  fill to the next: miles driven between them ÷ fuel used.
- **km/L** is the same measurement in kilometres per litre.
- **Δ mi.** ("delta miles") on a fuel row is the miles driven since the
  previous fill-up.
- **Unit Cost** on a fuel row is the price per litre.
- **Current odometer** on the Dashboard is the mileage from your most recent
  fuel entry.
- **Efficiency Bounds** (Settings): an MPG figure below the lower bound or
  above the upper bound is treated as a mistake and left out of the
  efficiency charts. Mistakes include a mistyped mileage and a fill-up that
  was never logged. The defaults, 10–100 MPG, suit most cars. Widen them for
  a plug-in hybrid (very high MPG) or for heavy towing (very low MPG).

---

## Something went wrong

**"I've forgotten the password."**
AutoLedger can't reset it by email. Ask the person who manages the server.
They can reset the sign-in, and you then create a new account. **Your cars,
entries, reminders and settings are all kept**, including the email and Home
Assistant set-up.

**"My MPG chart is empty, or has gaps."**
MPG needs two **full-tank** fills in a row with odometer readings. Check that
recent fill-ups have **Full tank** ticked and an **Odometer** figure. A reading
may also have been left out as implausible; see *Efficiency Bounds* above.

**"One MPG figure is wildly wrong."**
Usually a mistyped odometer reading, or a fill-up that was never logged. Find
the entry in **All Entries**, press **Edit**, and correct it. Adding a missing
fill-up with the right date also fixes it.

**"A reminder didn't email me."**
First check that the reminder has **Send notifications when due** ticked, then
press **Send test email** in **Settings → Notifications**. If the test fails,
the email settings need fixing (see the Setup help there). If the test works,
check the reminder's warning period: you're only alerted once it's within the
"Warn me" window. The daily check runs at the time in **Settings**.

**"A yearly reminder (MOT, insurance) still says overdue after I've done it."**
Repeating reminders only move on when you press **✓ Mark done** on them in
**Reminders**.

**"A mileage reminder never becomes due."**
Mileage comes from your latest fuel entry's odometer reading. If you haven't
logged fuel recently, or left the odometer blank, AutoLedger doesn't know the
car has done more miles.

**"The date on a new entry is yesterday's."**
Check **Settings → Time zone** is set to where you live and press **Save
settings**.

**"The page is blank, won't load, or says it can't connect."**
The server may be switched off or restarting. Wait a minute and refresh. If it
persists, tell whoever manages the server; your data is stored separately and
won't be lost.

**"I deleted something by mistake."**
Deleting can't be undone from the app. If you have a backup file from before
the deletion, use **Import AutoLedger JSON** to restore it. Only the missing
entries come back, and existing ones are skipped.

**"I imported LubeLogger history twice and now have duplicates."**
Use **Re-import CSV…** for that car. It clears the imported LubeLogger records
and brings them in once. Entries you typed in yourself are not affected.

If none of this helps, note down exactly what you see (a screenshot is ideal)
and pass it to whoever manages AutoLedger.

---

## Glossary

| Term | Meaning |
|---|---|
| **Active vehicle** | The car currently selected at the top of the menu; everything you see and add applies to it. |
| **Entry** | One recorded cost: a fill-up, a bill, a service. |
| **Category** | The kind of cost (Fuel, Insurance, Servicing & Repairs, Tax & Registration, or your own). |
| **Odometer** | The car's total mileage reading. |
| **Full tank** | Filled until the pump clicked off. Needed for MPG calculations. |
| **MPG** | Miles per (UK) gallon: higher is more economical. |
| **km/L** | Kilometres per litre: the metric equivalent of MPG. |
| **Δ mi.** | Miles driven since the previous fill-up. |
| **Reminder** | A warning for something due by a date and/or a mileage. |
| **Repeat / Mark done** | For regular jobs: pressing **✓ Mark done** moves the reminder on to its next due date or mileage. |
| **Backup (Export)** | A file containing all your AutoLedger data, for safekeeping. |
| **Restore (Import)** | Loading a backup file back into AutoLedger. |
| **LubeLogger** | Another car-cost app. AutoLedger can read its exported CSV files. |
| **CSV** | A simple spreadsheet-style file that many apps can export. |
| **Home Assistant** | A home-automation system. AutoLedger can show reminders on its dashboard and send phone alerts through it. |
| **Access token** | A long password-like code that lets AutoLedger talk to Home Assistant. |
| **App Password (Gmail)** | A separate password Google generates for apps like AutoLedger to send email. It is not your normal Gmail password. |
| **Time zone** | Where you are in the world. It decides when "today" starts and when the daily check runs. |
