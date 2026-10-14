/**
 * dynamic-style.js — aplica valores dinâmicos de estilo via CSSOM.
 *
 * A CSP (style-src sem 'unsafe-inline') bloqueia o atributo inline em innerHTML, mas permite
 * element.style.setProperty(). Templates emitem data-css="prop:valor;prop:valor" e este
 * módulo aplica as declarações (validadas pelo parser de CSS do navegador) em cada nó novo.
 */
function apply(el) {
  const spec = el.getAttribute('data-css');
  if (!spec) return;
  for (const decl of spec.split(';')) {
    const i = decl.indexOf(':');
    if (i < 1) continue;
    const prop = decl.slice(0, i).trim();
    const value = decl.slice(i + 1).trim();
    if (prop) el.style.setProperty(prop, value);
  }
}

function applyTree(node) {
  if (node.nodeType !== 1) return;
  if (node.hasAttribute('data-css')) apply(node);
  node.querySelectorAll('[data-css]').forEach(apply);
}

export function hydrateDynamicStyles(root = document) {
  applyTree(root.nodeType === 9 ? root.documentElement : root);
}

const observer = new MutationObserver((records) => {
  for (const r of records) {
    if (r.type === 'attributes') apply(r.target);
    else r.addedNodes.forEach(applyTree);
  }
});
observer.observe(document.documentElement, {
  childList: true, subtree: true, attributes: true, attributeFilter: ['data-css'],
});
hydrateDynamicStyles(document);
