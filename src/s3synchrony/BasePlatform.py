"""Contains the DataPlatformConnection class.

DataPlatformConnection - Default data platform class from which others should inherit.

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

import hashlib
import datetime as dt

from click import Path

import s3synchrony as s3s
import py_starter as ps
import dir_ops as do
import pandas as pd
from parent_class import ParentClass
import functools



def data_function( method ):

    @functools.wraps( method )
    def wrapper( self, Paths_inst ):

        successful_Paths = self.PATHS_CLASS()

        for Path_inst in Paths_inst: 
            if method( Path_inst ):
                successful_Paths._add( Path_inst )

        return successful_Paths

    return wrapper


class BasePlatform( ParentClass ):

    """Default class for data platforms.

    This class should only be instantiated as a backup case when unrecognized
    input is provided. Otherwise, this class should be used as an interface to
    be inherited from by future connections. All public methods listed here
    should be overridden by the child classes.
    """

    util_dir = '.BASE'

    DEFAULT_KWARGS = {
        'local_data_rel_dir': "Data",
        'remote_data_dir': "Data",
        'data_lDir': None,
        'data_rDir': None,
        '_name' : 'NONAME'
    }

    DIR_CLASS = do.Dir
    DIRS_CLASS = do.Dirs
    PATH_CLASS = do.Path
    PATHS_CLASS = do.Paths

    _file_colname = "File"
    _editor_colname = "Edited By"
    _time_colname = "Time Edited"
    _hash_colname = "Checksum"
    columns = [_file_colname, _editor_colname, _time_colname, _hash_colname]
    dttm_format = "%Y-%m-%d %H:%M:%S"


    def __init__(self, **kwargs):
        """Initialize necessary instance variables."""

        ParentClass.__init__( self )
        joined_kwargs = ps.merge_dicts( BasePlatform.DEFAULT_KWARGS, kwargs )
        self.set_atts( joined_kwargs )

        ###
        if not do.Dir.is_Dir( self.data_lDir ):
            self.data_lDir = do.Dir( s3s._cwd_Dir.join( self.local_data_rel_dir ) )

        #lDir is a local Dir, rDir is a remote dir
        self._util_lDir =  do.Dir( self.data_lDir.join(  self.util_dir ) )

        self._remote_versions_lPath = do.Path( self._util_lDir.join( 'versions_remote.csv' ) )
        self._local_versions_lPath =  do.Path( self._util_lDir.join( 'versions_local.csv' ) )

        self._remote_delete_lPath = do.Path( self._util_lDir.join( 'deleted_remote.csv' ) )
        self._local_delete_lPath = do.Path( self._util_lDir.join( 'deleted_local.csv' ) )

        self._tmp_lDir = do.Dir( self._util_lDir.join('tmp') )
        self._logs_lDir = do.Dir( self._util_lDir.join('logs') )
        self._ignore_lPath = do.Path( self._util_lDir.join( 'ignore_remote.txt' ) )

        self._ignore = []
        self._reset_approved = False

        ### These should be defined by the Child Platform
        self.data_rDir = None
        self._util_rDir = None
        self._util_deleted_rDir = None
        self._remote_versions_rPath = None
        self._remote_delete_rPath = None

        ### Get remote connection
        self._get_remote_connection()    


    def run( self ):

        self.intro_message()
        self.establish_connection()
        self.synchronize()
        self.close_message()

    def reset_all( self ):

        self.intro_message()
        self.establish_connection()
        if self.reset_confirm():
            self.reset_local()
            self.reset_remote()
        self.close_message()

    def intro_message(self):
        """Print an introductory message to signal program start."""
        print()
        print("###########################")
        print("#        Data Sync        #")
        print("###########################")
        print()

    def close_message(self):
        """Print a closing message to signal program end."""
        print()
        print("###########################")
        print("#       Done Syncing      #")
        print("###########################")

    def establish_connection(self):
        """Form a connection to the remote repository."""

        # Create local data dir
        if not self.data_lDir.exists():
            self.data_lDir.create() 
            print ('Directory not present, creating empty directory at: ')
            print (self.data_lDir)

        # Create platform util local dir
        if not self._util_lDir.exists():
            self._util_lDir.create()

        # Check if there is a .S3 subfolder in this S3 bucket/prefix
        if not self._util_rDir.exists():
            print("This S3 prefix has not been initialized for S3 Synchrony - Initializing prefix and uploading to S3...")
            self._initialize_util_rDir()
            print("Done.\n")

        has_local_lPaths =  self._local_versions_lPath.exists() and self._local_delete_lPath.exists()
        has_remote_lPaths = self._remote_versions_lPath.exists() and self._remote_delete_lPath.exists()

        if(not has_local_lPaths or not has_remote_lPaths):
            print( "Your data folder has not been initialized for S3 Synchrony - Downloading from S3..." )

            self._util_rDir.download( Destination = self._util_lDir )

            empty = pd.DataFrame( columns=self.columns )
            empty.to_csv( self._local_delete_lPath.path,      index=False)
            empty.to_csv( self._local_versions_lPath.path ,   index=False)
            
        self._tmp_lDir.create()
        self._logs_lDir.create()
        self._ignore_lPath.create()

        self._ignore = self._ignore_lPath.read().strip().split( '\n' ) #list of lines

    def _get_remote_connection( self ):

        self.conn = None

    def _initialize_util_rDir( self ):

        """Check for all necessary files on the S3 prefix for synchronization."""
        
        randhex = self._get_randomized_dirname()
        download_dir_loc = self._tmp_lDir.join( randhex )

        self.data_rDir.download( path = download_dir_loc )
        versions = self._compute_directory( download_dir_loc, False )

        self.data_lDir.create()
        self._util_lDir.create()

        versions.to_csv( download_dir_loc + '/' + self._remote_versions_lPath.filename, index = False )

        empty = pd.DataFrame( columns=self.columns )
        empty.to_csv(self._tmppath + '/' +
                     randhex + "/deletedS3.csv", index=False)

        self.resource.meta.client.upload_file(
            self._tmppath + '/' + randhex + "/versions.csv", self.aws_bkt, self._s3subdirremote + "versions.csv")
        self.resource.meta.client.upload_file(
            self._tmppath + '/' + randhex + "/deletedS3.csv", self.aws_bkt, self._s3subdirremote + "deletedS3.csv")

    def synchronize(self):
        """Prompt the user to synchronize all local files with remote files"""
        
        self._remote_versions_rPath.download( Destination = self._remote_versions_lPath )
        self._remote_delete_rPath.download( Destination = self._remote_delete_lPath )

        self._push_deleted_remote()
        self._pull_deleted_local()

        self._push_new_remote()
        self._pull_new_local()

        self._push_modified_remote()
        self._pull_modified_local()

        self._revert_modified_remote()
        self._revert_modified_local()

        self._remote_versions_rPath.upload( Destination = self._remote_versions_lPath )
        self._remote_delete_rPath.upload( Destination = self._remote_delete_lPath )

        # Save a snapshot of our current files into versionsLocal for next time
        self._compute_directory( self.data_lDir.path ).to_csv( self._local_versions_lPath.path, index=False )

        self.write_log()
        if self._log == '':
            self._log_lPath.remove( override = True )

    def _push_deleted_remote(self):

        """Remove remote files that were deleted locally."""
        mine, other, mod_mine, mod_other = self._compute_dfs(self.datapath)

        # Load in what files we had last time, and what files we have deleted in the past
        oldmine = pd.read_csv(self._localversionspath)
        deletedlocal = pd.read_csv(self._localdelpath)
        # Combine a list of files we have deleted and files we have had in the past, remove any duplicates
        deletedlocal = pd.concat([oldmine, deletedlocal])
        deletedlocal = deletedlocal.drop_duplicates(
            [self._file_colname], keep="last")
        # From previous files + deleted files select only the ones that AREN'T in our local system but ARE on AWS
        deletedlocal = deletedlocal[~deletedlocal[self._file_colname].isin(
            mine[self._file_colname])]
        deletedlocal = other[other[self._file_colname].isin(
            deletedlocal[self._file_colname])]

        deletedlocal.to_csv(self._localdelpath, index=False)

        if(len(deletedlocal) > 0):
            print(
                "UPLOAD: Would you like to delete these files on S3 that were deleted locally?:")
            print("('file name' / 'Date last modified on S3')\n")
            to_delete = []
            index = 0
            for i, row in deletedlocal.iterrows():
                to_delete.append(row[self._file_colname])
                print(index, row[self._file_colname], '\t',
                      row[self._time_colname], '\t by', row[self._editor_colname])
                index += 1

            selecteddelete = self._apply_selected_indices(
                self._delete_from_s3, to_delete)

            deleteds3 = pd.read_csv(self._s3delpath)
            newdeleted = other.loc[other[self._file_colname].isin(
                selecteddelete)]
            deleteds3 = pd.concat([deleteds3, newdeleted])
            deleteds3.to_csv(self._s3delpath)

            # Replace any removed file names with N/A and then drop if they have been deleted
            other[self._file_colname] = other[self._file_colname].where(
                ~other[self._file_colname].isin(selecteddelete))
            other = other.dropna()
            other.to_csv(self._s3versionspath, index=False)
            print("Done.\n")
  
    def _pull_deleted_local(self):
        """Remove files from local system that were deleted on S3."""
        mine, other, mod_mine, mod_other = self._compute_dfs(self.datapath)

        # Load in files deleted from S3, and select only those that ARE on our local system and AREN'T on AWS
        deleteds3 = pd.read_csv(self._s3delpath)
        deleteds3 = deleteds3[deleteds3[self._file_colname].isin(
            mine[self._file_colname])]
        deleteds3 = deleteds3[~deleteds3[self._file_colname].isin(
            other[self._file_colname])]

        if(len(deleteds3) > 0):
            print(
                "DOWNLOAD: Would you like to delete these files from your computer that were deleted on S3?:")
            print("('file name' / 'Date last modified locally')\n")
            to_delete = []
            index = 0
            for i, row in deleteds3.iterrows():
                to_delete.append(row[self._file_colname])
                mask = row[self._file_colname] == mine[self._file_colname]
                print(index, row[self._file_colname], '\t',
                      mine.loc[mask][self._file_colname].iloc[0])
                index += 1

            self._apply_selected_indices(self._delete_from_local, to_delete)
            print('Done.\n')

    def _push_new_remote(self):
        """Upload files to S3 that were created locally."""
        mine, other, mod_mine, mod_other = self._compute_dfs(self.datapath)

        # Find files that are in our directory but not AWS, and load in files deleted from AWS
        new_local = mine.loc[~mine[self._file_colname].isin(
            other[self._file_colname])]
        deletedfiles = pd.read_csv(self._s3delpath)[
            self._file_colname].values.tolist()

        if(len(new_local) > 0):
            print(
                "UPLOAD: Would you like to upload these new files to S3 that were created locally?:")
            print("('file name' / 'Date last modified Locally')\n")
            to_add = []
            index = 0
            for i, row in new_local.iterrows():
                to_add.append(row[self._file_colname])
                print(index, row[self._file_colname],
                      '\t', row[self._time_colname], end='\t')
                if(row[self._file_colname] in deletedfiles):
                    print("*DELETED ON S3", end='')
                print()
                index += 1

            selectedadd = self._apply_selected_indices(
                self._upload_to_s3, to_add)

            added_to_s3 = mine.loc[mine[self._file_colname].isin(selectedadd)]
            newversions = pd.concat([other, added_to_s3])
            newversions.to_csv(self._s3versionspath, index=False)
            print("Done.\n")



    def _pull_new_local(self):
        """Download files from S3 that were created recently."""
        mine, other, mod_mine, mod_other = self._compute_dfs(self.datapath)

        # Find files that are on S3 but not our local system and read in files we have deleted locally
        news3 = other.loc[~other[self._file_colname].isin(
            mine[self._file_colname])]
        deletedfiles = pd.read_csv(self._localdelpath)[
            self._file_colname].values.tolist()

        if(len(news3) > 0):
            print(
                "DOWNLOAD: Would you like to download these new files that were created on S3?:")
            print("('file name' / 'Date last modified on S3')\n")
            to_download = []
            index = 0
            for i, row in news3.iterrows():
                to_download.append(row[self._file_colname])
                print(index, row[self._file_colname], '\t', row[self._time_colname],
                      "\t by", row[self._editor_colname], end='\t')
                if(row[self._file_colname] in deletedfiles):
                    print("*DELETED LOCALLY", end='')
                print()
                index += 1

            self._apply_selected_indices(self._download_from_s3, to_download)
            print("Done.\n")

    def _push_modified_remote(self):
        """Update files on S3 with modifications that were made locally more recently."""
        mine, other, mod_mine, mod_other = self._compute_dfs(self.datapath)
        if(len(mod_mine) > 0):
            print(
                "UPLOAD: Would you like to update these files on S3 with your local changes?:")
            print(
                "('file name' / 'Date last modified locally' / 'Date last modified on S3')\n")
            self._push_sequence(mod_mine, mine, other)

    def _pull_modified_local(self):
        """Update local files with modifications that were made on S3 more recently."""
        mine, other, mod_mine, mod_other = self._compute_dfs(self.datapath)
        if(len(mod_other) > 0):
            print(
                "DOWNLOAD: Would you like to update these local files with the changes from S3?:")
            print(
                "('file name' / 'Date last modified locally' / 'Date last modified on S3')\n")
            self._pull_sequence(mod_other, other)

    def _revert_modified_remote(self):

        """Revert remote files with modifications that were made locally less recently."""

        mine, other, mod_mine, mod_other = self._compute_dfs(self.datapath)
        if(len(mod_other) > 0):
            print( "UPLOAD: Would you like to revert these files on S3 back to your local versions?:")
            print( "('file name' / 'Date last modified locally' / 'Date last modified on S3')\n")
            self._push_sequence(mod_other, mine, other)


    def _revert_modified_local(self):
        """Revert local files with modifications that were made on S3 less recently."""
        mine, other, mod_mine, mod_other = self._compute_dfs(self.datapath)
        if(len(mod_mine) > 0):
            print(
                "DOWNLOAD: Would you like to revert these local files back to the versions on S3?:")
            print(
                "('file name' / 'Date last modified locally' / 'Date last modified on S3')\n")
            self._pull_sequence(mod_mine, other)


    def _compute_dfs(self, lDir ):
        """Return a list of dfs containing all the information for smart_sync."""
        
        mine = self._compute_directory( lDir )
        other = pd.read_csv( self._remote_versions_lPath.path )

        mine = self._filter_ignore( mine )
        other = self._filter_ignore( other )

        inboth = mine[ mine[self._file_colname].isin( other[self._file_colname]) ]

        mod_mine = []  # Files more recently modified Locally
        mod_other = []  # Files more recently modified on S3

        for file in inboth[self._file_colname]:
            mycs = inboth.loc[inboth[self._file_colname] == file][self._hash_colname].iloc[0]
            othercs = other.loc[other[self._file_colname] == file][self._hash_colname].iloc[0]

            if(mycs != othercs): # users have pushed conflicting file check sums

                datemine = dt.datetime.strptime(
                    mine.loc[mine[self._file_colname] == file][self._time_colname].iloc[0], self.dttm_format)
                dateother = dt.datetime.strptime(
                    other.loc[other[self._file_colname] == file][self._time_colname].iloc[0], self.dttm_format)
                if(datemine > dateother):
                    mod_mine.append([file, datemine, dateother])
                else:
                    mod_other.append([file, datemine, dateother])

        return (mine, other, mod_mine, mod_other)

    def _compute_directory(self, lDir, ignore_util=True):
        """Create a dataframe describing all files in a local directory."""

        df = pd.DataFrame(columns=self.columns)

        folders_to_skip = [ self.util_dir ]
        if not ignore_util:
            folders_to_skip = []

        Paths_inst = lDir.walk_contents_Paths( block_dirs=True, block_paths=False, folders_to_skip = folders_to_skip )

        for Path_inst in Paths_inst:

            df_new = pd.DataFrame( columns = self.columns )
            df_new[ self._file_colname ] = [Path_inst.get_rel( lDir ).path  ]
            df_new[ self._time_colname ] = Path_inst.get_mtime().strftime( self.dttm_format )
            df_new[ self._hash_colname ] = self._hash( Path_inst.path )
            df_new[ self._editor_colname ] = self._name

            df = pd.concat([df, df_new], ignore_index=True)

        return df

    def _filter_ignore(self, df ):
        """Remove all files that should be ignored as requested by the user."""

        return df.loc[ ~df[self._file_colname].isin( self._ignore ) ]      

    @data_function
    def _upload_to_remote( self, lPath ):

        rel_lPath = lPath.get_rel( self.data_lDir )
        rPath = self.data_rDir.join_Path( rel_lPath )
        
        return rPath.upload( Destination = lPath )

    @data_function
    def _download_from_remote(self, rPath):

        rel_rPath = rPath.get_rel( self.data_rDir )
        lPath = self.data_lDir.join_Path( rel_rPath )
        
        return rPath.download( Destination = lPath )

    @ps.confirm_wrap('Are you sure you want to delete these files?')
    @data_function
    def _delete_from_remote(self, rPaths):

        """Attempt to delete every file provided from the remote S3 prefix."""

        successful_Paths = self.PATHS_CLASS()

        print("Are you sure you want to delete these files from S3?")
        if ps.confirm_raw():

            for rPath in rPaths:
                
                rel_rPath = rPath.get_rel( self.data_rDir ) 
                deleted_rPath = self._util_deleted_rDir.join_Path( rel_rPath )

                # make a copy of the deleted file into the deleted folder in the util section
                if rPath.copy( Destination = deleted_rPath, override = True ):
                    if rPath.delete( override = True ):
                        successful_Paths._add( rPath )

        return successful_Paths

    @data_function
    def _delete_from_local(self, lPaths):

        """Attempt to delete every file requested from our local data folder."""
        
        print("Are you sure you want to delete these files from your computer?")
        if ps.confirm_raw():

            for lPath in lPaths:
                lPath.remove( override = True )

    def _apply_selected_indices(self, data_function, Paths_inst):

        """Prompt the user to select certain files to perform a synchronization function on."""

        indicies = ps.get_user_selection_for_list_items( Paths_inst,
                                                            prompt = 'Enter number to select corresponding files, "all" for all files, enter to exit',
                                                            exceptions= ['all'] )

        if 'all' in indicies:
            indicies = list(range(len(Paths_inst)))

        selected_Paths = self.PATHS_CLASS()
        for ind in indicies:
            selected_Paths._add( Paths_inst.Objs[ ind ] )

        successful_Paths = data_function( selected_Paths )
        return successful_Paths

    def _push_sequence(self, listfiles, mine, other):
        """User-prompted uploading of files from a dataframe."""
        to_push = []
        index = 0
        for file in listfiles:
            to_push.append(file[0])
            print(index, file[0], '\t', file[1], '\t', file[2], "\t by",
                  other.loc[other[self._file_colname] == file[0]][self._editor_colname].iloc[0])
            index += 1
        selectedpush = self._apply_selected_indices(
            self._upload_to_s3, to_push)

        updatedins3 = mine.loc[mine[self._file_colname].isin(
            selectedpush)]
        newversions = pd.concat([other, updatedins3])
        newversions = newversions.drop_duplicates(
            [self._file_colname], keep="last").sort_index()
        newversions.to_csv(self._s3versionspath, index=False)
        print("Done.\n")


 
    def _pull_sequence(self, listfiles, other):

        """User-prompted downloading of files from a dataframe."""

        to_pull = []
        index = 0
        for file in listfiles:
            to_pull.append(file[0])
            print(index, file[0], '\t', file[1], '\t', file[2], "\t by",
                  other.loc[other[self._file_colname] == file[0]][self._editor_colname].iloc[0])
            index += 1
        self._apply_selected_indices(self._download_from_s3, to_pull)
        print("Done.\n")

 

    def reset_confirm(self) -> bool:

        """Prompt the user to confirm whether a reset can occur."""

        print('Are you sure you would like to reset the remote data directory?')
        print('This will not change any of your file contents, but will delete the entire')
        confirm = input( str(self.util_dir) + ' folder on your local computer and on your AWS prefix: ' + self.aws_prfx + ' (y/n): ')

        if confirm.lower() != 'y':
            print("Reset aborted.")
            self._reset_approved = False

        self._reset_approved = True
        return self._reset_approved

    def reset_local(self):

        """Remove all modifications made locally by synchronization."""

        if self._reset_approved:
            self._util_lDir.remove( override = True )
        else:
            print("Cannot reset local -- user has not approved.")


    def reset_remote(self):
        """Remove all modifications made to the remote repo by synchronization."""
        
        if self._reset_approved:
            self._util_rDir.remove( override = True )
        else:
            print("Cannot reset remote -- user has not approved.")

    def _get_randomized_dirname(self):
        """Generate a random string to be used as a file name."""
        return hashlib.md5(bytes(str(dt.datetime.now()), "utf-8")).hexdigest()

    def _hash(self, filepath):
        """Return a unique checksum based on a file's contents."""
        file = open(filepath, "rb")
        data = file.read()
        return hashlib.md5(data).hexdigest()
