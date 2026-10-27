"""Jinja filesystem loading with native Windows separators for extended paths."""
import os
from pathlib import Path

from jinja2 import FileSystemLoader, TemplateNotFound
from jinja2.loaders import split_template_path

from .filesystem_paths import filesystem_path


class NativeTemplateLoader(FileSystemLoader):
    def get_source(self, environment, template):
        pieces = split_template_path(template)
        # A drive or alternate data stream must never change the search root.
        if os.name == 'nt' and any(':' in piece for piece in pieces):
            raise TemplateNotFound(template)
        for directory in self.searchpath:
            filename = filesystem_path(Path(directory).joinpath(*pieces))
            try:
                source = filename.read_text(encoding=self.encoding)
                modified = filename.stat().st_mtime
            except (FileNotFoundError, IsADirectoryError, PermissionError):
                continue

            def uptodate(path=filename, stamp=modified):
                try:
                    return path.stat().st_mtime == stamp
                except OSError:
                    return False

            return source, str(filename), uptodate
        raise TemplateNotFound(template)
