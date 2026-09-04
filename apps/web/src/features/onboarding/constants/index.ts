import type { ProfessionOption, Question } from "../types";

export const HOLO_CARD_HEIGHT = 470;
export const HOLO_CARD_WIDTH = 330;

export const professionOptions: ProfessionOption[] = [
  { label: "Student", value: "student" },
  { label: "Teacher", value: "teacher" },
  { label: "Engineer", value: "engineer" },
  { label: "Developer", value: "developer" },
  { label: "Designer", value: "designer" },
  { label: "Manager", value: "manager" },
  { label: "Consultant", value: "consultant" },
  { label: "Entrepreneur", value: "entrepreneur" },
  { label: "Researcher", value: "researcher" },
  { label: "Writer", value: "writer" },
  { label: "Artist", value: "artist" },
  { label: "Doctor", value: "doctor" },
  { label: "Lawyer", value: "lawyer" },
  { label: "Accountant", value: "accountant" },
  { label: "Sales", value: "sales" },
  { label: "Marketing", value: "marketing" },
  { label: "Analyst", value: "analyst" },
  { label: "Freelancer", value: "freelancer" },
  { label: "Retired", value: "retired" },
  { label: "Other", value: "other" },
];

export const FIELD_NAMES = {
  NAME: "name",
  RAYON: "rayon",
  PROFESSION: "profession",
  GMAIL: "gmail",
  FOCUS: "focus",
} as const;

// HyperFix : les deux rayons gérés aujourd'hui (rayons.json côté gamme-engine).
// La vérification stricte reste serveur (gamme_mon_rayon) au premier usage.
export const rayonOptions: ProfessionOption[] = [
  { label: "Épicerie salée", value: "epicerie-salee" },
  { label: "Frais surgelé", value: "frais-surgele" },
];

export const questions: Question[] = [
  {
    id: "1",
    question: "Hey! I'm GAIA. What should I call you?",
    placeholder: "Enter your name...",
    fieldName: FIELD_NAMES.NAME,
  },
  {
    id: "2",
    question:
      "Quel rayon gères-tu ? C'est ton espace de travail HyperFix (stocks négatifs, anomalies, récap quotidien).",
    placeholder: "Épicerie salée, Frais surgelé...",
    fieldName: FIELD_NAMES.RAYON,
    chipOptions: rayonOptions.map((r) => ({
      label: r.label,
      value: r.value,
    })),
  },
  {
    id: "3",
    question:
      "What do you do? This helps me handle your emails, calendar, and tasks the right way.",
    placeholder: "e.g., Software Developer, Student, Designer...",
    fieldName: FIELD_NAMES.PROFESSION,
  },
  {
    id: "4",
    question:
      "Last thing. Connect your Gmail and I'll go through your inbox, find what matters, and set up your first action items.",
    placeholder: "",
    fieldName: FIELD_NAMES.GMAIL,
  },
];
