"""Perform functionality for synchronizing and resetting with a repo.

get_supported_platforms - Get a list of all data platforms supported currently
smart_sync - Synchronizes all local files with a remote repository through user input
reset_all - Completely resets both local and remote repos with user input confirmation

  Typical usage example (for S3):

  import s3synchrony as s3s
  params = {}
  params["datafolder"] = "Data"
  params["aws_bkt"] = "analytics_development"
  params["aws_prfx"] = "S3_Synchrony_Testing"
  if(len(sys.argv) > 1 and sys.argv[1] == "reset"):
      s3s.reset_all(**params)
  else:
      s3s.smart_sync(**params)

Copyright (C) 2022  Sevan Brodjian
Created for Ameren at the Ameren Innovation Center @ UIUC

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import s3synchrony as s3s
import py_starter as ps

_supported_platforms = { "s3": s3s.Platforms.s3.Platform }


def get_supported_platforms():
    """Return a list of the supported data platforms."""
    return [*_supported_platforms]

def get_connection( platform, **kwargs ):

    if(platform in _supported_platforms):
        connection = _supported_platforms[platform](**kwargs)
        return connection

    else:
        print ('No platform {platform} available'.format( platform = platform ) )
        return None


def smart_sync( platform = "s3", **kwargs):

    """Perform all necessary steps to synchronize a local repository with a remote repo."""

    connection = get_connection( **kwargs )
    connection.run()

def get_template():

    #list_contents_Paths()
    module_Paths = s3synchrony.templates_Dir.list_contents_Paths( block_paths=False,block_dirs=True )
    module_Path = ps.get_selection_from_list( module_Paths )
    return module_Path.import_module()


def reset_all( **kwargs ):

    """Reset local and remote directories to original state."""

    connection = get_connection( **kwargs )
    connection.reset_all()

def run():

    if s3synchrony.json_Path.exists():
        sync_params = ps.json_to_dict( s3synchrony.json_Path.read() )
        module = get_template()
        module.run( sync_params )
    else:
        print ('No sync JSON file')


if __name__ == '__main__':
    run()
