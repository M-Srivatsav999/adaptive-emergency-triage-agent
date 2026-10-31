# Keeping it free for the people who need it

The goal is a tool that rural families and health workers can use at no cost. This is how the project is set up for that, and
what to watch out for.

## What already makes it free
* **MIT licence** (code) and **CC BY 4.0** (knowledge content) - anyone may copy, share and adapt it (see `LICENSE`, `NOTICE.md`).
* **No running costs**: it works offline on one ordinary computer. No cloud, no subscription, no API fees.
* **No adverts, no analytics, no data collection**: patient text never leaves the machine.

## Suggested ways to distribute (all free)
1. **Public repository** (e.g. GitHub) with each release as a downloadable zip - `README.md` explains setup.
2. **USB / SD-card bundle** for clinics without internet: the project folder plus the Docker images and Ollama models
   (see `docs/OFFLINE_DEPLOYMENT.md`, "Fully air-gapped install").
3. **Hand-over to health workers** through the clinician(s) who review it, with a short training session.

## Before sharing widely - please do these
* **Get the review done.** Share the review sheet with the clinician (`docs/CLINICIAN_REVIEW_GUIDE.md`). Until entries are
  approved, say honestly that the content is draft. The app shows each entry's review status on every result.
* **Start supervised.** Begin with one clinic or health worker who can check the output, and record disagreements with the
  built-in feedback endpoint. Expand only after a review of how it performed.
* **Talk to your college/guide** about ownership, the licence choice and permission to publish - this is a university project.
* **Understand the rules for health software.** In India, software that gives health advice can fall under medical-device
  rules, and handling health data is covered by data-protection law. Ask your college or a legal/regulatory adviser; the
  tool says clearly it is decision support, but that statement alone may not settle the legal position.
* **App stores** have their own rules for health apps; web/offline distribution avoids those while you validate.
* **"Free" does not remove responsibility**: a wrong answer can still harm someone. That is why the system errs toward
  urgency, never says ROUTINE for something it cannot place, and always shows emergency numbers.

## Costs you may still have
Your time; optional hardware (a spare PC or mini-computer per clinic); nothing per user.
