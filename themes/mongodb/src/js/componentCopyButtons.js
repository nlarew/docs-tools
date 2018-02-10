// For dev purposes I totally changed this module. Before commit, this
// file should be restored to its HEAD state and the current contents
// should be migrated to a new module. This might require a small class
// name change since copyable-code will be overloaded.

function nodeListToArray(nodeList) {
    return Array.prototype.slice.call(nodeList);
}

export function setup() {
    const copyableBlocks = document.getElementsByClassName('copyable-code');
    for (const copyBlock of copyableBlocks) {
        const highlightElement = copyBlock.getElementsByClassName('highlight')[0];
        if (!highlightElement) {
            return;
        }

        const text = highlightElement.innerText.trim();
        const copyButtonContainerNodes = nodeListToArray(copyBlock.previousElementSibling.childNodes);
        const copyButton = copyButtonContainerNodes.filter(
            (child) => child.nodeName === 'A'
        )[0];

        // const copyButton = document.createElement('button');
        // const copyIcon = document.createElement('span');
        // copyButtonContainer.className = 'copy-button-container';
        // copyIcon.className = 'fa fa-clipboard';
        // copyButton.className = 'copy-button';
        // copyButton.appendChild(copyIcon);
        // copyButton.appendChild(document.createTextNode('Copy'));
        // copyButtonContainer.appendChild(copyButton);
        // highlightElement.insertBefore(copyButtonContainer, highlightElement.children[0]);

        copyButton.addEventListener('click', () => {
            const tempElement = document.createElement('textarea');
            tempElement.style.position = 'fixed';
            document.body.appendChild(tempElement);
            tempElement.value = text;
            tempElement.select();

            try {
                const successful = document.execCommand('copy');
                if (!successful) {
                    throw new Error('Failed to copy');
                }
            } catch (err) {
                console.error('Failed to copy');
                console.error(err);
            }

            document.body.removeChild(tempElement);
        });
    }
}
