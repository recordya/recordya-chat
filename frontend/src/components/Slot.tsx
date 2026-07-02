/**
 * Slot component for rendering plugin-injected UI.
 *
 * Renders all components registered for the given slot.
 */
import { slotRegistry, type SlotName, type SlotContext } from "@/plugins/SlotRegistry";

interface SlotProps {
  name: SlotName;
  context: SlotContext;
}

export function Slot({ name, context }: SlotProps) {
  const components = slotRegistry.getComponents(name, context);

  if (components.length === 0) {
    return null;
  }

  return (
    <>
      {components.map((Component, i) => (
        <Component key={i} {...context} />
      ))}
    </>
  );
}
