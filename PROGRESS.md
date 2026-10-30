# AegisShield — Progress

A plain-language record of what has been built, stage by stage. No jargon without an explanation.

There are three documents in this project and they do different jobs:

| File | What it is for |
|---|---|
| `README.md` | How to run the thing. Instructions. |
| `LEARNING-LOG.md` | Why it is built this way. Long and detailed. |
| **`PROGRESS.md`** (this file) | **What we have done so far, in simple words.** One section per stage. |

---

## Where things stand right now

**Stage 1 is finished.** The project has a working local development environment: a message queue and a database that start with one command on your own computer.

**There is no application code yet.** Nothing detects fraud yet. Stage 1 built the foundation that the actual program will run on top of.

---

## Stage 1 — The local development environment

**Status: complete.** 45 of 45 planned tasks done. Finished 31 October 2026.

### In one sentence

We set up the two pieces of supporting software the fraud-detection system will need — a message queue and a database — so that any developer can start them both on their own machine with a single command.

### What problem this solves

AegisShield is going to be a fraud detection system. The plan is:

1. A program called the **Producer** sends out transaction events ("card 1234 just spent $500").
2. Those events wait in a **queue**.
3. A program called the **Worker** picks them up, checks them for fraud, and saves the results to a **database**.

None of those programs exist yet. But all of them will need the queue and the database to exist first. And every developer needs the *same* queue and the *same* database, set up the same way, or bugs appear that only happen on one person's computer.

That is the problem Stage 1 solves: everyone gets an identical environment, with no manual setup.

### What we actually built

One main file, 59 lines long, called `docker-compose.yml`. It describes two pieces of software:

- **RabbitMQ** — the message queue. Software that holds messages until another program is ready to collect them.
- **PostgreSQL** — the database. Software that stores information in tables so you can search it later.

Plus three supporting files:

- `.env.example` — a list of nine settings (usernames, passwords, port numbers) with working defaults.
- `.env` — your own private copy of those settings. Deliberately not shared or uploaded anywhere.
- `README.md` — the instructions.

### How you use it

Two commands, and you are done:

```
cp .env.example .env
docker compose up -d --wait
```

The first command makes your private settings file. The second starts both pieces of software and waits until they are actually ready.

You do not install a database. You do not install a message queue. You do not configure anything. Everything runs inside **containers** — see the concepts section below.

### What we proved works, and how

We did not just build it and assume it worked. Every claim below was tested:

| What we claimed | How we proved it |
|---|---|
| One command starts everything | Ran it from a completely empty machine state |
| It says "ready" only when it really is ready | Froze the database and checked it got reported as broken |
| Your data survives a restart | Saved a row, restarted, checked it was still there — 5 times in a row |
| There is a clean way to wipe everything | Wiped it and confirmed it came back empty — 5 times in a row |
| A port clash fails with a clear message | Deliberately blocked the port and timed the failure |
| Missing settings give a useful error | Deleted the settings file and read the error message |
| No passwords get uploaded to GitHub | Checked the entire history of the project, not just today |
| A future program can plug into this | Built a throwaway test program that connected to both |
| Nothing is lost if the computer is killed | Killed both programs outright and checked the data |

### Key numbers

| Measurement | Result | Target |
|---|---|---|
| Starting from scratch, including downloads | **45 seconds** | under 5 minutes |
| Starting again later | **14 seconds** | under 1 minute |
| Failing when a port is already in use | **1.8 seconds** | under 10 seconds |

### What does NOT exist yet

Being honest about this matters, because it is easy to look at a working environment and assume the product is built.

- **No Producer and no Worker.** No fraud detection. No application code at all.
- **No database tables.** The database is created, but it is empty.
- **No automated tests**, and nothing runs checks automatically when code changes.
- **Nothing about putting this on a real server.** This runs on one developer's laptop only. All the passwords are obvious placeholders, on purpose.

### Things that went wrong, and what we learned

Worth recording, because these are the useful parts:

1. **We used a file path that used to be correct.** PostgreSQL version 18 changed where it stores its data. We used the path from older versions, which every tutorial on the internet still shows. The database refused to start. Lesson: when you lock software to a specific version, that protects you from surprise changes — it does **not** mean what you remember about that software is still true.

2. **A test said "it took 72 seconds" when it really took 2.** The timer was started and stopped by hand in a terminal, so it was measuring how fast someone types. Lesson: a measurement is only as good as your understanding of what was actually measured.

3. **One of our own review findings was wrong.** An automated review tool concluded, with confident reasoning, that killing a container would make it restart itself. We wrote that into three documents. Then we actually ran it and the containers stayed dead. Lesson: reading code and reasoning about it finds contradictions between documents very well, but it cannot establish facts about how other software behaves. Only running it can do that.

4. **Our test scripts were wrong more often than the thing being tested.** Four separate times a test reported a failure that turned out to be a bug in the test. Lesson: a test that cries wolf is as much of a problem as a test that misses a real fault.

---

## Explaining this to someone else

### The 30-second version

> "I'm building a fraud detection system. Right now I've finished the foundation — the local setup that the actual program will run on.
>
> The system will have two parts that talk to each other through a message queue, and store results in a database. Before writing either part, I set up that queue and that database so they run in containers on any developer's machine with one command, identically every time.
>
> The point is that nobody has to install or configure anything, and nobody gets the 'works on my machine' problem. It starts in about 14 seconds, and I verified the data survives restarts and that it never reports itself as ready before it actually is."

### The 2-minute version, if they want more

> "The project is a fraud detection system. The design is that one program publishes transaction events, those events go into a message queue, and a second program reads from the queue, checks each transaction for fraud, and writes the result to a database.
>
> I started with the infrastructure rather than the code, because both programs depend on it. So the first stage was getting RabbitMQ — that's the message queue — and PostgreSQL — the database — running reliably on a developer machine.
>
> It's all defined in one configuration file, so the setup is the same for everyone and it's version-controlled. Two commands and you have a working environment. No installing a database by hand.
>
> The part I spent the most care on was making it honest about its own state. Containers can report that they've started while the software inside still isn't accepting connections, so the start command waits for a real connection test instead of just checking the process exists. I tested that by freezing the database and confirming the system reported it as broken rather than healthy.
>
> I also verified the things you'd want verified: data survives restarts, there's a clean reset, passwords aren't committed to the repo, and a new service can plug in without changing what's there. The next stage is writing the actual programs."

### If they ask "what was hard about it?"

> "The honest answer is that most of the difficulty wasn't the configuration, it was finding out where my assumptions were wrong.
>
> One example: PostgreSQL changed where it stores data in version 18, and I used the path from older versions. It's the path in every tutorial. The database just refused to start. Four seconds of checking the actual image would have told me, and instead I debugged it.
>
> The one I found most interesting: an automated review flagged one of my tests as impossible, with a confident explanation. I believed it and changed three documents. Later I ran the actual experiment and the review was wrong. The lesson I took is that reviewing documents is good at catching places where two documents disagree, but it can't tell you how someone else's software actually behaves. For that you have to run it."

### If they ask "is it finished?"

Do not overclaim. The accurate answer:

> "The infrastructure stage is finished and tested. The application itself isn't written yet — that's the next stage. So there's a working, verified foundation, and no fraud detection logic on top of it yet."

---

## Simple concepts, in plain words

If any of the words above were unfamiliar, this is the whole vocabulary you need.

**Container.** A box that holds a program plus everything it needs to run — the right version of the software, the right settings, the right supporting files. Because the box includes everything, the program behaves the same on any computer. You can throw the box away and make a new one in seconds. This is why nobody has to install a database by hand.

**Image.** The template a container is made from. Like a blueprint. You make a container from an image.

**Pinning a version.** Saying "use exactly PostgreSQL 18.4", not "use the newest one". If you say "newest", your project can break overnight because someone else released an update. Two developers could also end up with different software from the same instructions.

**Message queue.** A waiting line for messages. One program drops a message in; another picks it up when it's ready. The useful part is that the two programs don't have to be running at the same time, or at the same speed. If the second one is busy or restarting, messages wait instead of being lost.

**Database.** Software that stores information in tables and lets you search it. Here it keeps the results of fraud checks.

**Volume.** Storage that outlives the container. Containers are disposable — delete one and anything inside it is gone. A volume is kept separately, so the database's data survives. This is why you can restart the environment without losing everything.

**Healthcheck.** A small test the system runs over and over on a running program, to answer "is this actually working?" rather than just "is it switched on". For the database it's a real attempt to connect. This distinction matters more than it sounds: a program can be running and still not ready, and if your system lies about that, the next program fails for no visible reason.

**Port.** A numbered door on your computer that a program listens at. The database uses 5432 and the queue uses 5672. Only one program can hold a door at a time, which is why there's a clear error and a way to change the number if something else already has it.

**Environment variables.** Settings kept outside the code — usernames, passwords, port numbers. The code says "use the password" and the setting says what the password is. This means the real passwords never get written into files that get shared, and different people can use different settings without editing the project.

**Docker Compose.** The tool that reads one file describing several containers and runs them together as a group. One command starts everything in the right order.

---

## The pattern for the next stage

Each stage gets a section in this file, added below Stage 1, with the same parts:

1. **In one sentence** — what the stage did.
2. **What problem this solves** — why it was worth doing.
3. **What we actually built** — the files and pieces, named plainly.
4. **How you use it** — the commands.
5. **What we proved works, and how** — claims next to the evidence.
6. **Key numbers** — anything measured.
7. **What does NOT exist yet** — stated plainly, no overclaiming.
8. **Things that went wrong, and what we learned.**
9. **Explaining this to someone else** — the 30-second and 2-minute versions, updated to include the new stage.
10. **Any new concepts**, in plain words.

The "where things stand right now" box at the top gets rewritten each time.
