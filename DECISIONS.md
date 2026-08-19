# StudyFlow — Design & Engineering Decisions

## Product Direction

StudyFlow is designed as a focused AI study workspace that combines
study notes, AI tutoring, quizzes, and PDF export in one application.

The landing page was designed to explain the product quickly while also
showing the actual product workflow.

## Visual Direction

I chose a minimal editorial-style interface with:

- Serif display headings
- Blue accent color
- Warm neutral backgrounds
- Thin borders and ruled sections
- Simple, restrained animations

The goal was to make the interface feel focused and suitable for studying
rather than looking like a generic AI dashboard.

## Product Demonstration

The homepage includes an interactive demonstration with three variants:

- Study Note
- Quiz
- AI Chat

The demonstration is intended to show how the main StudyFlow features work
without requiring the visitor to read a long feature description.

## AI Architecture

AI functionality is designed around a locally running Ollama model.

This allows the application to use a local language model for AI-related
operations such as tutoring and quiz generation.

## Backend

Flask is used for:

- Application routing
- Sessions
- Server-side rendering
- Connecting the frontend with application features

## Data Storage

SQLite is used to store application data such as:

- Notes
- Quiz history
- Chat history

## PDF Export

ReportLab is used to generate formatted PDF documents from study notes.

## Responsive Design

The landing page was tested at:

- 390px mobile width
- 1440px desktop width

The layout was adjusted to prevent horizontal scrolling and maintain
readability at both sizes.

## Dark Mode

Dark mode was retained as an optional visual theme.

The dark Aurora background was adjusted so its animation does not create
horizontal page overflow.

## Claims and Content

Unsupported performance numbers and exaggerated product claims were removed
from the landing page.

The page now focuses on features and technologies that can be demonstrated
and explained during the project review.

## Ownership

The project and landing-page implementation were developed and customized
for StudyFlow by Karthikeya.