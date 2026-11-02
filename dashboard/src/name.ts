/** The assistant's name (persona.yaml on the laptop), learned from /api/state; shown in the UI text. */
let current = "Sanae";

export const assistantName = () => current;
export function setAssistantName(name: string | undefined) {
  if (name) current = name;
}
