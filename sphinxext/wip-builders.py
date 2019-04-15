import abc
import logging
import sys
import uuid
from sphinx.util.osutil import relative_uri
from sphinx.builders.html import StandaloneHTMLBuilder, DirectoryHTMLBuilder
from sphinx import addnodes
import json

logger = logging.getLogger("fasthtml")

TOC_EXCLUDED = [
    "genindex",
    "search"
]

def is_http(url):
    return url.startswith("http://") or url.startswith("https://")

class TreeNode:
    __metaclass__ = abc.ABCMeta

    def __init__(self):
        self._id = uuid.uuid4().hex
    def __eq__(self, other):
        return self._id == other._id
    def __getitem__(self, key):
        return getattr(self, key)
    @abc.abstractproperty
    def lineage_item(self):
        """Get a list of the name, slug, and link for this node."""
    @abc.abstractproperty
    def lineage(self):
        """Get a list of the name, slug, and link for this node and all ancestors."""
    def is_a(self, test_class):
        return isinstance(self, test_class)

class Page(TreeNode):
    def __init__(self, title, slug, parent):
        self.title = title
        self.slug = slug
        self.parent = parent  # A Page or Section that contains this Page
        self.children = []

    @property
    def lineage_item(self):
        return {
            "title": self.title,
            "slug": self.slug,
            "link": self.slug
        }

    @property
    def lineage(self):
        lineage = self.parent.lineage
        if isinstance(self.parent, Page):
            # Pages don't include themselves in their lineage
            # so if the parent is a Page we need to manually add its lineage item.
            lineage.append(self.parent.lineage_item)
        return lineage

class Section(TreeNode):
    def __init__(self, defined_on=None, label=None, entries=[]):
        self.is_root = False  # bool: True if this doesn't have a parent section.
        self.defined_on = defined_on  # str: slug of the page this was defined on
        self.parent = None  # The Section that contains this one, if not root
        self.label = label  # str: The section label
        self.children = [Page(title, slug, parent=self) for title, slug in entries]

    @staticmethod
    def create_from(toctree):
        """Create a new Section from a toctree node."""
        section = Section(
            parent=toctree["parent"],
            entries=toctree["entries"],
            caption=toctree["caption"],
        )
        return section

    @property
    def lineage_item(self):
        return {
            "text": self.caption,
            "slug": self.parent,
            "link": self.child_pages[0] if self.is_root else None # Link to Overview pages
        }

    @property
    def lineage(self):
        lineage = self.parent.lineage if self.parent else []
        lineage.append(self.lineage_item)
        return lineage

    @property
    def child_pages(self):
        return [child for child in self.children if child.is_a(Page)]

    @property
    def child_sections(self):
        return [child for child in self.children if child.is_a(Section)]

    @property
    def descendants(self):
        """Get all Pages and Sections that have this Section as an ancestor."""
        return self.children + [child.descendants for child in self.children]

    @property
    def descendant_pages(self):
        """Get all Pages that have this Section as an ancestor."""
        return [d for d in self.descendants if d.is_a(Page)]

    @property
    def descendant_sections(self):
        """Get all Sections that have this Section as an ancestor."""
        return [d for d in self.descendants if d.is_a(Section)]

    @property
    def siblings(self):
        return [c for c in self.parent.children if c._id != self._id] if self.parent else []

    @property
    def sibling_pages(self):
        return [sibling for sibling in self.siblings if sibling.is_a(Page)]

    @property
    def sibling_sections(self):
        return [sibling for sibling in self.siblings if sibling.is_a(Section)]

    def has_relation(self, relation, candidate):
        """Returns a boolean indicating whether this Section has the specified relationship to the candidate Node"""
        relation_pages = {
            "ancestor": self.descendant_pages,
            "sibling": self.sibling_pages,
            "parent": self.child_pages,
        }[relation]
        relation_sections = {
            "ancestor": self.descendant_sections,
            "sibling": self.sibling_sections,
            "parent": self.child_sections,
        }[relation]

        if type(candidate) == str:
            # Assume that this candidate is a slug
            return candidate in [r.slug for r in relation_pages]
        elif isinstance(candidate, Page):
            return candidate in relation_pages
        elif isinstance(candidate, Section):
            return candidate in relation_sections
        else:
            raise Exception(
                "Section can only be a {} of a Page, Section, or slug. ".format(relation)
                "Instead, received a {}".format(type(candidate))
            )

    def is_ancestor_of(self, candidate):
        return self.has_relation("ancestor", candidate)

    def is_parent_of(self, candidate):
        return self.has_relation("parent", candidate)

    def is_sibling_of(self, candidate):
        return self.has_relation("sibling", candidate)

    def is_descendant_of(self, candidate):
        return candidate.is_ancestor_of(self)

    def is_child_of(self, candidate):
        return candidate.is_parent_of(self)

    def get_child(self, slug=None, _id=None):
        if not slug and not _id:
            raise Exception("You must specify either a slug or an _id value.")
        if slug and _id:
            raise Exception("You cannot specify both a slug and an _id value.")

        if slug:
            find_operator = "slug"
            candidates = [c for c in self.child_pages if c.slug == slug]
        if _id:
            find_operator = "_id"
            candidates = [c for c in self.children if c._id == _id]
        if len(candidates):
            return candidates[0]
        else:
            raise Exception("Could not find a child with the specified {}.".format(find_operator))

    def add_descendant_section(self, section):
        successfully_added_section = False  # Track our success through the recursive stack
        # We haven't added the descendant section as a child of any
        # section yet, so we have to check if we have the page it was
        # defined on as a child instead.
        if self.is_parent_of(section.defined_on):
            if section.label:
                # The candidate Section is a direct child of this Section
                section.parent = self
                self.children.append(section)
            else:
                # The candidate Section is the direct child of one of this section's child Pages
                child_page = self.get_child(section.defined_on)
                section.parent = child_page
                child_page.children.append(section)
            successfully_added_section = True
        # Check if the Section's parent is one of our descendants
        else:
            for section in self.child_sections:
                successfully_added_section = section.add_descendant_section(section)
                if successfully_added_section:
                    break
        return successfully_added_section


class TableOfContents:
    def __init__(self, render_title, get_relative_uri):
        # Helper callbacks from the parent Builder
        self.render_title = render_title
        self.get_relative_uri = get_relative_uri

        self.sections = []

    def compile(self):
        # Get all toctree nodes
        doctree = env.get_doctree(docname)
        toctrees = [toctreenode for toctreenode in doctree.traverse(addnodes.toctree)]

    def initialize(self, env, docname=None):
        if self.initialized:
            return
        # Determine if we're at the root of the toctree
        is_root_stage = True if docname is None else False
        if root_stage:
            docname = env.config.master_doc
            self.root = docname

        toctree_nodes = self.fetch_toctree_nodes(env, docname);
        toc_sections = [TocSection.create_from(toctree) for toctree in toctree_nodes]
        for section in toc_sections:
            self.add_section(section)

        if root_stage:
            self.initialized = True


class Toctree:
    def __init__(self, render_title, get_relative_uri):
        # Helper callbacks from the parent Builder
        self.render_title = render_title
        self.get_relative_uri = get_relative_uri

        self.initialized = False

        self.sections = []
        self.root = None

    def render(self, format="html"):
        return "<span>Hello from the Toctree!</span>"

    def fetch_toctree_nodes(self, env, docname):
        # Get all toctree nodes
        doctree = env.get_doctree(docname)
        toctree_nodes = [toctreenode for toctreenode in doctree.traverse(addnodes.toctree)]
        return toctree_nodes

    def is_root_section(self, section):
        return section.parent == self.root

    def add_root_section(self, section):
        section.is_root = True
        self.sections.append(section)

    def add_section(self, section):
        try:
            if self.is_root_section(section):
                self.add_root_section(section)
            else:
                # Attempt to add the section within one of our child sections
                for child_section in self.sections:
                    section_was_added = child_section.add_descendant_section(section)
                    if section_was_added:
                        break
                else:
                    raise Exception(
                        "Sections must be root or nested inside of a root section."
                    )
        except Exception as e:
            self.app.warn("Failed to add section:\n{}".format(e))

    def initialize_section_pages(self, section):
        for child_page in section.child_pages:
            if not is_http(child_page.slug):
                self.initialize(env, child_page.slug)

    def initialize(self, env, docname=None):
        if self.initialized:
            return
        # Determine if we're at the root of the toctree
        is_root_stage = True if docname is None else False
        if root_stage:
            docname = env.config.master_doc
            self.root = docname

        toctree_nodes = self.fetch_toctree_nodes(env, docname);
        toc_sections = [TocSection.create_from(toctree) for toctree in toctree_nodes]
        for section in toc_sections:
            self.add_section(section)

        if root_stage:
            self.initialized = True



class FastHTMLBuilder(StandaloneHTMLBuilder, FastHTMLMixin):
    name = "html"
    allow_parallel = False

    def init(self):
        StandaloneHTMLBuilder.init(self)
        self.toctree = Toctree(self._render_title, self.get_relative_uri)

    def handle_page(
        self,
        docname,
        addctx,
        templatename="page.html",
        outfilename=None,
        event_arg=None,
    ):
        self.toctree.initialize(self.env)
        StandaloneHTMLBuilder.handle_page(self, docname, addctx, templatename=templatename, outfilename=outfilename, event_arg=event_arg)

    def _get_local_toctree(self, docname, collapse=True, **kwds):
        if "includehidden" not in kwds:
            kwds["includehidden"] = False

        toctree_html = "".join(self.toctree.html(docname))
        return toctree_html
