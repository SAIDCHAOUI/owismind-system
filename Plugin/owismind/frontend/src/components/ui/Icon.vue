<script setup>
// Single icon primitive — replaces the maquette's `OWI.iconStr(name)` + innerHTML
// pattern with one reusable component. SVGs are inline, use `currentColor`, and
// are sized by the `size` prop (defaults to 1em so the icon scales with text).
//
// XSS note: the SVG comes from a COMPILE-TIME constant registry (icons.js), never
// from user/LLM input, so v-html here is safe by construction. User/agent content
// is never rendered through this component.
import { computed } from 'vue'
import { iconStr } from './icons.js'

const props = defineProps({
  name: { type: String, required: true },
  // Any CSS length; number is treated as px. Controls the square box size.
  size: { type: [String, Number], default: '1em' },
})

const svg = computed(() => iconStr(props.name))
const boxSize = computed(() =>
  typeof props.size === 'number' ? `${props.size}px` : props.size,
)
</script>

<template>
  <span
    class="ui-icon"
    :style="{ width: boxSize, height: boxSize }"
    aria-hidden="true"
    v-html="svg"
  />
</template>

<style scoped>
.ui-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  line-height: 0;
}
.ui-icon :deep(svg) {
  width: 100%;
  height: 100%;
  display: block;
}
</style>
