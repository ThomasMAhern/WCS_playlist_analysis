import streamlit as st
import polars as pl
import psutil

pl.Config.set_tbl_rows(100).set_fmt_str_lengths(100)

regex_year_first = r'\d{2,4}[.\-/ ]?\d{1,2}[.\-/ ]?\d{1,2}'
regex_year_last = r'\d{1,2}[.\-/ ]?\d{1,2}[.\-/ ]?\d{2,4}'
regex_year_abbreviated = r"'\d{2}"

def gen(iterable):
    '''converts iterable item to generator to save on memory'''
    for _ in iterable:
        yield _

def wcs_specific(df_):
  '''given a df, filter to the records most likely to be west coast swing related'''
  return (df_.lazy()
          .filter(~(pl.col('playlist_name').str.contains(regex_year_first)
                  |pl.col('playlist_name').str.contains(regex_year_last)
                  |pl.col('playlist_name').str.contains(regex_year_abbreviated)
                  |pl.col('playlist_name').str.to_lowercase().str.contains('wcs|social|party|soirée|west coast|westcoast|routine|practice|practise|westie|party|beginner|bpm|swing|novice|intermediate|comp|musicality|timing|pro show')))
      )

@st.cache_resource #makes it so streamlit doesn't have to reload for every sesson.
def load_playlist_data():
        return (pl.scan_parquet('data_playlists_*.parquet')
      .rename({'name':'playlist_name'})
      #makes a new column filled with a date - this is good indicator if there was a set played
      .with_columns(extracted_date = pl.concat_list(pl.col('playlist_name').str.extract_all(regex_year_last),
                                                    pl.col('playlist_name').str.extract_all(regex_year_last),
                                                    pl.col('playlist_name').str.extract_all(regex_year_abbreviated),)
                                       .list.unique().list.sort(),
                    song_url = pl.when(pl.col('track.id').is_not_null())
                                 .then(pl.concat_str(pl.lit('https://open.spotify.com/track/'), 'track.id')),
                    playlist_url = pl.when(pl.col('playlist_id').is_not_null())
                                 .then(pl.concat_str(pl.lit('https://open.spotify.com/playlist/'), 'playlist_id')),
                    owner_url = pl.when(pl.col('owner.id').is_not_null())
                                 .then(pl.concat_str(pl.lit('https://open.spotify.com/user/'), 'owner.id')),
                    region = pl.col('location').str.split(' - ').list.get(0, null_on_oob=True),
                    country = pl.col('location').str.split(' - ').list.get(1, null_on_oob=True),)
      
      #gets the counts of djs, playlists, and geographic regions a song is found in
      .with_columns(dj_count = pl.n_unique('owner.display_name').over(['track.id', 'track.name']),
                    playlist_count = pl.n_unique('playlist_name').over(['track.id', 'track.name']),
                    regions = pl.col('region').over('track.name', mapping_strategy='join')
                                  .list.unique()
                                  .list.sort()
                                  .list.join(', '),
                    countries = pl.col('country').over('track.name', mapping_strategy='join')
                                  .list.unique()
                                  .list.sort()
                                  .list.join(', '),
                    song_position_in_playlist = pl.concat_str(pl.col('song_number'), pl.lit('/'), pl.col('tracks.total'), ignore_nulls=True),
                    apprx_song_position_in_playlist = pl.when((pl.col('song_number')*100 / pl.col('tracks.total')) <= 33)
                                                        .then(pl.lit('beginning'))
                                                        .when((pl.col('song_number')*100 / pl.col('tracks.total')) > 33,
                                                                (pl.col('song_number')*100 / pl.col('tracks.total')) <= 66)
                                                        .then(pl.lit('middle'))
                                                        .when((pl.col('song_number')*100 / pl.col('tracks.total')) > 66)
                                                        .then(pl.lit('end')),
                                                        )
      .with_columns(geographic_region_count = pl.when(pl.col('regions').str.len_bytes() != 0)
                                                .then(pl.col('regions').str.split(', ').list.len())
                                                .otherwise(0))
      )


@st.cache_resource
def load_lyrics():
        return pl.scan_parquet('song_lyrics_*.parquet')

@st.cache_resource #makes it so streamlit doesn't have to reload for every sesson.
def load_notes():
        return pl.scan_csv('data_notes.csv').rename({'Artist':'track.artists.name', 'Song':'track.name'})

@st.cache_data
def load_countries():
        return sorted(df.select('country').unique().drop_nulls().collect(streaming=True)['country'].to_list())

@st.cache_data
def load_stats():
        '''makes it so streamlit doesn't have to reload for every sesson/updated parameter
        should make it much more responsive'''
        song_count = df.select(pl.concat_str('track.name', pl.lit(' - '), 'track.id')).unique().collect(streaming=True).shape[0]
        wcs_song_count = df.pipe(wcs_specific).select(pl.concat_str('track.name', pl.lit(' - '), 'track.id')).unique().collect(streaming=True).shape[0]
        artist_count = df.select('track.artists.name').unique().collect(streaming=True).shape[0]
        wcs_artist_count = df.pipe(wcs_specific).select('track.artists.name').unique().collect(streaming=True).shape[0]
        playlist_count = df.select('playlist_name').unique().collect(streaming=True).shape[0]
        wcs_playlist_count = df.pipe(wcs_specific).select('playlist_name').collect(streaming=True).unique().shape[0]
        dj_count = df.select('owner.display_name').unique().collect(streaming=True).shape[0]
        
        return song_count, wcs_song_count, artist_count, wcs_artist_count, playlist_count, wcs_playlist_count, dj_count

df = load_playlist_data()
df_lyrics = load_lyrics()
df_notes = load_notes()
countries = load_countries()
stats = load_stats()










st.write(f"Memory Usage: {psutil.virtual_memory().percent}%")
st.markdown("## Westie Music Database:")
st.text("Note: this database lacks most of the non-spotify playlists - but if you know a DJ, pass this to them and tell them they should put their playlists on spotify so we can add them to the collection! (a separate playlist by date is easiest for me ;) )\n")

st.write(f"{stats[0]:,} Songs ({stats[1]:,} wcs specific)")
st.write(f"{stats[2]:,} Artists ({stats[3]:,} wcs specific)")
st.write(f"{stats[4]:,} Playlists ({stats[5]:,} wcs specific)")
st.write(f"{stats[6]:,} DJ's/Westies\n\n")

st.markdown(f"#### ")






data_view_toggle = st.toggle("📊 Raw data")

if data_view_toggle:
        num_records = st.slider("How many records?", 1, 1000, 50)
        st.dataframe(df._fetch(num_records), 
                 column_config={"song_url": st.column_config.LinkColumn(),
                                "playlist_url": st.column_config.LinkColumn(),
                                "owner_url": st.column_config.LinkColumn()})
        st.markdown(f"#### ")










st.markdown("#### ")
st.markdown("#### Choose your own adventure!")

@st.cache_data
def top_songs():
        '''creates the standard top songs until user '''
        return (df
                 .join(df_notes,
                        how='full',
                        on=['track.artists.name', 'track.name'])
                .group_by('track.name', 'song_url', 'playlist_count', 'dj_count')
                .agg(pl.n_unique('playlist_name').alias('matching_playlist_count'), 
                     'playlist_name', 'track.artists.name', 'owner.display_name', 'country',
                     'apprx_song_position_in_playlist', 'track.artists.id', 'notes', 'note_source', 
                        #connies notes
                        'Starting energy', 'Ending energy', 'BPM', 'Genres', 'Acousticness', 'Difficulty', 'Familiarity', 'Transition type')
                .with_columns(pl.col('playlist_name', 'track.artists.id', 'owner.display_name', 
                                     'apprx_song_position_in_playlist', 'track.artists.name', 'country',
                                        #connies notes
                                        'Starting energy', 'Ending energy', 'BPM', 'Genres', 'Acousticness', 'Difficulty', 
                                        'Familiarity', 'Transition type'
                                        ).list.unique().list.drop_nulls().list.sort().list.head(50),
                                pl.col('notes', 'note_source').list.unique().list.sort().list.drop_nulls(),
                                )
                .select('track.name', 'song_url', 'playlist_count', 'dj_count', 
                        pl.all().exclude('track.name', 'song_url', 'playlist_count', 'dj_count',))
                .sort('matching_playlist_count', descending=True)
                .head(1000).collect(streaming=True)
                )
top_songs = top_songs()

#courtesy of Vishal S
song_locator_toggle = st.toggle("🎵 Find a Song")
if song_locator_toggle:
        song_col1, song_col2 = st.columns(2)
        with song_col1:
                song_input = st.text_input("Song name:").lower()
                artist_name = st.text_input("Artist name:").lower()
                dj_input = st.text_input("DJ/user name:").lower()
                playlist_input = st.text_input("Playlist name (try 'late night', '80', or 'beginner'):").lower().split(',')
        with song_col2:
                countries_selectbox = st.multiselect("Country:", countries)
                added_2_playlist_date = st.text_input("Added to playlist date (yyyy-mm-dd):")
                track_release_date = st.text_input("Track release date (yyyy-mm-dd or '198' for 1980's music):")
                # anti_playlist_input = st.text_input("Not in playlist:").lower().split(',')
        
        # if ''.join(anti_playlist_input).strip() == '':
        anti_playlist_input = ['this_is_a_bogus_value_to_hopefully_not_break_things']

        if (song_input + artist_name + dj_input + ''.join(playlist_input) + ''.join(anti_playlist_input) +
            ''.join(countries_selectbox) + added_2_playlist_date + track_release_date).strip() == 'this_is_a_bogus_value_to_hopefully_not_break_things':
                # st.text('preloaded')
                st.dataframe(top_songs, 
                                 column_config={"song_url": st.column_config.LinkColumn()}
                            )

        else:
                st.dataframe(df
                        .join(df_notes,
                                how='full',
                                on=['track.artists.name', 'track.name'])
                        .filter(pl.col('track.name').str.to_lowercase().str.contains(song_input),
                                pl.col('track.artists.name').str.to_lowercase().str.contains(artist_name),
                                pl.col('playlist_name').str.to_lowercase().str.contains_any(playlist_input),
                                # ~pl.col('playlist_name').str.to_lowercase().str.contains_any(anti_playlist_input), #courtesy of Tobias N.
                                pl.col('owner.display_name').str.to_lowercase().str.contains(dj_input),
                                pl.col('country').str.contains('|'.join(countries_selectbox)), #courtesy of Franzi M.
                                pl.col('added_at').dt.to_string().str.contains(added_2_playlist_date), #courtesy of Franzi M.
                                pl.col('track.album.release_date').dt.to_string().str.contains(track_release_date), #courtesy of James B.
                                )
                        .group_by('track.name', 'song_url', 'playlist_count', 'dj_count')
                        .agg(pl.n_unique('playlist_name').alias('matching_playlist_count'), 
                        'playlist_name', 'track.artists.name', 'owner.display_name', 'country',
                        'apprx_song_position_in_playlist', 'track.artists.id', 'notes', 'note_source', 
                                #connies notes
                                'Starting energy', 'Ending energy', 'BPM', 'Genres', 'Acousticness', 'Difficulty', 'Familiarity', 'Transition type')
                        .with_columns(pl.col('playlist_name', 'track.artists.id', 'owner.display_name', 
                                        'apprx_song_position_in_playlist', 'track.artists.name', 'country',
                                                #connies notes
                                                'Starting energy', 'Ending energy', 'BPM', 'Genres', 'Acousticness', 'Difficulty', 
                                                'Familiarity', 'Transition type'
                                                ).list.unique().list.drop_nulls().list.sort().list.head(50),
                                        pl.col('notes', 'note_source').list.unique().list.sort().list.drop_nulls(),
                                        hit_terms = pl.col('playlist_name')
                                                        .list.join(', ')
                                                        .str.to_lowercase()
                                                        .str.extract_all('|'.join(playlist_input))
                                                        .list.drop_nulls()
                                                        .list.unique()
                                                        .list.sort(),
                                        )
                        .select('track.name', 'song_url', 'playlist_count', 'dj_count', 'hit_terms', 
                                pl.all().exclude('track.name', 'song_url', 'playlist_count', 'dj_count', 'hit_terms'))
                        .sort([pl.col('hit_terms').list.len(), 
                        'matching_playlist_count'], descending=True)
                        .head(1000).collect(streaming=True), 
                        column_config={"song_url": st.column_config.LinkColumn()}
                        )
        st.markdown(f"#### ")

#courtesy of Vishal S
playlist_locator_toggle = st.toggle("💿 Find a Playlist")
if playlist_locator_toggle:
        playlist_col1, playlist_col2 = st.columns(2)
        with playlist_col1:
                playlist_input = st.text_input("Playlist name:").lower()
                song_input = st.text_input("Contains the song:").lower()
        with playlist_col2:
                dj_input = st.text_input("DJ name:").lower()
        
        if any(val for val in [playlist_input, song_input, dj_input]):
                st.dataframe(df
                        .filter(pl.col('playlist_name').str.to_lowercase().str.contains(playlist_input),
                                pl.col('track.name').str.to_lowercase().str.contains(song_input),
                                pl.col('owner.display_name').str.to_lowercase().str.contains(dj_input))
                        .group_by('playlist_name', 'playlist_url')
                        .agg('owner.display_name', pl.n_unique('track.name').alias('song_count'), pl.n_unique('track.artists.name').alias('artist_count'), 'track.name')
                        .with_columns(pl.col('owner.display_name', 'track.name').list.unique().list.sort(),)
                        .head(200).collect(streaming=True), 
                        column_config={"playlist_url": st.column_config.LinkColumn()}
                        )
        st.markdown(f"#### ")






@st.cache_data
def djs_data():
        return (df
                .group_by('owner.display_name', 'owner_url')
                .agg(pl.n_unique('track.name').alias('song_count'),
                     pl.n_unique('track.artists.name').alias('artist_count'),
                     pl.n_unique('playlist_name').alias('playlist_count'),
                     'playlist_name', 
                     )
                .with_columns(pl.col('playlist_name')
                              .list.unique()
                              .list.drop_nulls()
                              .list.sort()
                              .list.head(50)
                              )
                .sort(pl.col('playlist_count'), descending=True)
                .head(1000)
                .collect(streaming=True)
                )

djs_data = djs_data()


#courtesy of Lino V
search_dj_toggle = st.toggle("🎧 DJ insights")

if search_dj_toggle:
        dj_col1, dj_col2 = st.columns(2)
        with dj_col1:
                id_input = st.text_input("DJ name/ID (ex. Kasia Stepek or 1185428002)")
                dj_id = id_input.lower().strip()
        with dj_col2:
                dj_playlist_input = st.text_input("DJ playlist name:").lower()
        
        if (dj_id + dj_playlist_input).strip() == '':
                st.dataframe(djs_data, 
                 column_config={"owner_url": st.column_config.LinkColumn()})
        
        else:
                st.dataframe(df
                        .filter((pl.col('owner.display_name').str.to_lowercase().str.contains(dj_id)
                                |pl.col('owner.id').str.to_lowercase().str.contains(dj_id))
                                &pl.col('playlist_name').str.to_lowercase().str.contains(dj_playlist_input),
                                )
                        .group_by('owner.display_name', 'owner_url')
                        .agg(pl.n_unique('track.name').alias('song_count'),
                        pl.n_unique('track.artists.name').alias('artist_count'),
                        pl.n_unique('playlist_name').alias('playlist_count'),
                        'playlist_name', 
                        )
                        .with_columns(pl.col('playlist_name')
                                .list.eval(pl.when(pl.element().str.to_lowercase().str.contains(dj_playlist_input))
                                                .then(pl.element()))
                                .list.unique()
                                .list.drop_nulls()
                                .list.sort()
                                .list.head(50)
                                )
                        .sort(pl.col('playlist_count'), descending=True)
                        .head(1000)
                        .collect(streaming=True), 
                        column_config={"owner_url": st.column_config.LinkColumn()}
                        )
        
        
        # elif dj_id:
                st.text(f"Popular music _{id_input}_ doesn't play")
                ##too much data now that we have more music, that list is blowing up the streamlit
                others_music = (df
                                .filter(~(pl.col('owner.id').str.to_lowercase().str.contains(dj_id)
                                        | pl.col('owner.display_name').str.to_lowercase().str.contains(dj_id)))
                                .select('track.name', 'owner.display_name', 'dj_count', 'playlist_count', 'song_url')
                                )

                djs_music = (df
                        .filter((pl.col('owner.id').str.to_lowercase().str.contains(dj_id)
                                | pl.col('owner.display_name').str.to_lowercase().str.contains(dj_id)))
                        .select('track.name', 'owner.display_name', 'dj_count', 'playlist_count', 'playlist_name', 'song_url')
                        .unique()
                        )
                
                st.dataframe(others_music.join(djs_music, how='anti', 
                                on=['track.name', 'dj_count', 
                                'playlist_count', 'song_url'])
                        .group_by(pl.all().exclude('owner.display_name'))
                        .agg('owner.display_name')
                        .with_columns(pl.col('owner.display_name').list.head(50))
                        .sort('dj_count', 'playlist_count', descending=True)
                        .head(200)
                        .collect(streaming=True), 
                        column_config={"song_url": st.column_config.LinkColumn()})
        
        
        
        
        
        
                st.text(f"Music unique to _{id_input}_")
                st.dataframe(djs_music.join(others_music, 
                                        how='anti', 
                                        on=['track.name', 'owner.display_name', 
                                                'dj_count', 'playlist_count', 'song_url'])
                        .group_by(pl.all().exclude('playlist_name'))
                        .agg('playlist_name')
                        .sort('playlist_count', descending=True)
                        .filter(pl.col('dj_count').eq(1))
                        .head(100)
                        .collect(streaming=True), 
                        column_config={"song_url": st.column_config.LinkColumn()})
                

        st.markdown(f"#### Compare DJ's:")
        dj_list = sorted(df.select('owner.display_name').unique().drop_nulls().collect(streaming=True)['owner.display_name'].to_list())
        
        # st.dataframe(df
        #                 .group_by('owner.display_name')
        #                 .agg(song_count = pl.n_unique('track.name'), 
        #                         playlist_count = pl.n_unique('playlist_name'), 
        #                         dj_count = pl.n_unique('owner.display_name'),
        #                         )
        #                 .sort('owner.display_name')
        #                 .collect(streaming=True)
        #         )
        djs_selectbox = st.multiselect("Compare these DJ's music:", dj_list)

        if len(djs_selectbox) >= 2:
                st.dataframe(df
                        .filter(pl.col('owner.display_name').str.contains_any(djs_selectbox))
                        .group_by('owner.display_name')
                        .agg(song_count = pl.n_unique('track.name'), 
                                playlist_count = pl.n_unique('playlist_name'), 
                                )
                        .sort('owner.display_name')
                        .collect(streaming=True)
                )


                dj_1_df = (df
                        .filter(pl.col('owner.display_name') == djs_selectbox[0],
                                ~(pl.col('owner.display_name') == djs_selectbox[1]),)
                        .select('track.name', 'song_url', 'dj_count', 'playlist_count')
                        .unique()
                        )
                dj_2_df = (df
                        .filter(pl.col('owner.display_name') == djs_selectbox[1],
                                ~(pl.col('owner.display_name') == djs_selectbox[0]))
                        .select('track.name', 'song_url', 'dj_count', 'playlist_count')
                        .unique()
                        )
                st.text(f"Music _{djs_selectbox[0]}_ has, but _{djs_selectbox[1]}_ doesn't.")
                st.dataframe(dj_1_df.join(dj_2_df, 
                                                how='anti', 
                                                on=['track.name', 'song_url', 
                                                'dj_count', 'playlist_count']
                                                )
                                .unique()
                                .sort('dj_count', descending=True)
                                .head(300).collect(streaming=True) ,
                                # ._fetch(10000),
                                column_config={"song_url": st.column_config.LinkColumn()})
                st.text(f"Music _{djs_selectbox[1]}_ has, but _{djs_selectbox[0]}_ doesn't")
                st.dataframe(dj_2_df.join(dj_1_df, 
                                                how='anti', 
                                                on=['track.name', 'song_url', 
                                                'dj_count', 'playlist_count']
                                                )
                                .unique()
                                .sort('dj_count', descending=True)
                                .head(300).collect(streaming=True) ,
                                # ._fetch(10000),
                                column_config={"song_url": st.column_config.LinkColumn()})
        st.markdown(f"#### ")



















@st.cache_data
def region_data():
    return (df
                 .group_by('region')
                 .agg(song_count = pl.n_unique('track.name'), 
                      playlist_count = pl.n_unique('playlist_name'), 
                      dj_count = pl.n_unique('owner.display_name'),
                      djs = pl.col('owner.display_name'),
                      )
                 .with_columns(pl.col('djs').list.unique().list.head(50))
                 .sort('region')
                 .collect(streaming=True)
                 )

@st.cache_data
def country_data():
        return (df
                 .group_by('country')
                 .agg(song_count = pl.n_unique('track.name'), 
                      playlist_count = pl.n_unique('playlist_name'), 
                      dj_count = pl.n_unique('owner.display_name'),
                      djs = pl.col('owner.display_name'),
                      )
                 .with_columns(pl.col('djs').list.unique().list.head(50))
                 .sort('country')
                 .collect(streaming=True)
                 )





#courtesy of Lino V
geo_region_toggle = st.toggle("🌎 Geographic Insights")
if geo_region_toggle:
    st.markdown(f"\n\n\n#### Region-Specific Music:")
    st.text(f"Disclaimer: Insights are based on available data and educated guesses - which may not be accurate or representative of reality.")
    
    st.dataframe(region_data())
    st.dataframe(country_data())
    regions = ['Select One', 'Europe', 'North America', 'MENA', 'Oceania', 'Asia']
    region_selectbox = st.selectbox("Which Geographic Region would you like to see?",
                                    regions)

    if region_selectbox != 'Select One':
        st.markdown(f"#### What are the most popular songs only played in {region_selectbox}?")
        europe = (df
                #  .pipe(wcs_specific)
                .filter(pl.col('region') == region_selectbox,
                        pl.col('geographic_region_count').eq(1))
                .group_by('track.name', 'song_url', 'dj_count', 'playlist_count', 'region', 'geographic_region_count')
                .agg(pl.col('owner.display_name').unique())
                # .unique()
                .sort('dj_count', descending=True)
                )
        
        st.dataframe(europe._fetch(50000), 
                        column_config={"song_url": st.column_config.LinkColumn()})




    st.markdown(f"#### Comparing Countries' music:")
    countries_selectbox = st.multiselect("Compare these countries' music:", countries)
    
    if len(countries_selectbox) >= 2:
        
        countries_df = df.filter(pl.col('country').str.contains_any(countries_selectbox),
                                pl.col('dj_count').gt(3), 
                                pl.col('playlist_count').gt(3))

        country_1_df = (countries_df
                .filter(pl.col('country') == countries_selectbox[0],
                        ~(pl.col('country') == countries_selectbox[1]),)
                .select('track.name', 'song_url', 'dj_count', 'playlist_count')
                .unique()
                )
        country_2_df = (countries_df
                .filter(pl.col('country') == countries_selectbox[1],
                        ~(pl.col('country') == countries_selectbox[0]))
                .select('track.name', 'song_url', 'dj_count', 'playlist_count')
                .unique()
                )
        # st.dataframe(country_1_df._fetch(10000))
        st.text(f"{countries_selectbox[0]} music not in {countries_selectbox[1]}")
        st.dataframe(country_1_df.join(country_2_df, 
                                        how='anti', 
                                        on=['track.name', 'song_url', 
                                        'dj_count', 'playlist_count']
                                        )
                        .unique()
                        .sort('dj_count', descending=True)
                        .head(300).collect(streaming=True) ,
                        # ._fetch(10000),
                        column_config={"song_url": st.column_config.LinkColumn()})
        st.text(f"{countries_selectbox[1]} music not in {countries_selectbox[0]}")
        st.dataframe(country_2_df.join(country_1_df, 
                                        how='anti', 
                                        on=['track.name', 'song_url', 
                                        'dj_count', 'playlist_count']
                                        )
                        .unique()
                        .sort('dj_count', descending=True)
                        .head(300).collect(streaming=True) ,
                        # ._fetch(10000),
                        column_config={"song_url": st.column_config.LinkColumn()})
        st.markdown(f"#### ")













#courtesy of Vincent M
songs_together_toggle = st.toggle("Songs most played together")

if songs_together_toggle:
        song_combo_col1, song_combo_col2 = st.columns(2)
        with song_combo_col1:
                song_input = st.text_input("Song Name/ID:")
        with song_combo_col2:
                artist_name_input = st.text_input("Song artist name:").lower()
                
        song_input_prepped = song_input.lower()

        # st.dataframe(df
        #         .select('song_number', 'track.name', 'playlist_name', 'track.id', 'playlist_url', 'owner.display_name', 'track.artists.id'
        #                 )
        #         .unique()
        #         .sort('playlist_url', 'song_number')
                
        #         .with_columns(pair1 = pl.when(pl.col('song_number').shift(-1) > pl.col('song_number'))
        #                                 .then(pl.concat_str(pl.col('track.name'), pl.lit(': '), pl.col('track.id'), pl.lit(' --- '),
        #                                                         pl.col('track.name').shift(-1), pl.lit(': '), pl.col('track.id').shift(-1),
        #                                                         )),
        #                         pair2 = pl.when(pl.col('song_number').shift(1) < pl.col('song_number'))
        #                                 .then(pl.concat_str(pl.col('track.name').shift(-1), pl.lit(': '), pl.col('track.id').shift(1), pl.lit(' --- '),
        #                                                         pl.col('track.name'), pl.lit(': '), pl.col('track.id'),
        #                                                         )),
        #                         )
        #         .with_columns(pair = pl.concat_list('pair1', 'pair2'))
        #         .explode('pair')
        #         .select('pair', 'playlist_name', 'owner.display_name', 'track.artists.id',
        #                 )
        #         .drop_nulls()
        #         .unique()
        #         .with_columns(pl.col('pair').str.split(' --- ').list.sort().list.join(' --- '))
        #         .group_by('pair')
        #         .agg(pl.n_unique('playlist_name').alias('times_played_together'), 'playlist_name', 'owner.display_name', 'track.artists.id',
        #                 )
        #         .with_columns(pl.col('playlist_name').list.unique(),
        #                         pl.col('owner.display_name').list.unique())
        #         .filter(~pl.col('playlist_name').list.join(', ').str.contains_any(['The Maine', 'delete', 'SPOTIFY']),
        #                 pl.col('times_played_together').gt(1),
        #                 )
        #         .filter(pl.col('pair').str.to_lowercase().str.contains(song_input_prepped),
        #                 pl.col('track.artists.id').list.join(', ').str.to_lowercase().str.contains(artist_name_input)
        #                 )
        #         .with_columns(pl.col('pair').str.split(' --- '))
        #         .sort('times_played_together',
        #                 pl.col('owner.display_name').list.len(), 
        #                 descending=True)
        #         .head(100).collect(streaming=True), 
        #          column_config={"playlist_url": st.column_config.LinkColumn()}
        #         )
    
    
    
    
        if (song_input_prepped + artist_name_input).strip() != '':
                st.markdown(f"#### Most common songs to play after _{song_input}_:")
    
                st.dataframe(df
                        .select('song_number', 'track.name', 'playlist_name', 'track.id', 'song_url', 
                                'owner.display_name', 'track.artists.name', 'track.artists.id',
                                )
                        .unique()
                        .sort('playlist_name', 'song_number')
                        
                        .with_columns(pair1 = pl.when(pl.col('song_number').shift(-1) > pl.col('song_number'))
                                                .then(pl.concat_str(pl.col('track.name'), pl.lit(': '), pl.col('track.id'), pl.lit(' --- '),
                                                                        pl.col('track.name').shift(-1), pl.lit(': '), pl.col('track.id').shift(-1),
                                                                        )),
                                        pair2 = pl.when(pl.col('song_number').shift(1) < pl.col('song_number'))
                                                .then(pl.concat_str(pl.col('track.name').shift(-1), pl.lit(': '), pl.col('track.id').shift(1), pl.lit(' --- '),
                                                                        pl.col('track.name'), pl.lit(': '), pl.col('track.id'),
                                                                        )),
                                        )
                        .with_columns(pair = pl.concat_list('pair1', 'pair2'))
                        .explode('pair')
                        .select('pair', 'playlist_name', 'owner.display_name', 'track.artists.name', 'track.name', 'song_url',
                                )
                        .drop_nulls()
                        .unique()
                        .with_columns(pl.col('pair').str.split(' --- ').list.sort().list.join(' --- '))
                        .group_by('pair')
                        .agg(pl.n_unique('playlist_name').alias('times_played_together'), 'playlist_name', 
                        'owner.display_name', 'track.artists.name', 'track.name', 'song_url')
                        .with_columns(pl.col('playlist_name').list.unique(),
                                        pl.col('owner.display_name').list.unique())
                        .filter(~pl.col('playlist_name').list.join(', ').str.contains_any(['The Maine', 'delete', 'SPOTIFY']),
                                pl.col('times_played_together').gt(1),
                                )
                        .filter(pl.col('pair').str.split(' --- ').list.get(0, null_on_oob=True).str.to_lowercase().str.contains(song_input_prepped),
                                pl.col('track.artists.name').list.join(', ').str.to_lowercase().str.contains(artist_name_input))
                        .with_columns(pl.col('pair').str.split(' --- '))
                        .sort('times_played_together',
                                pl.col('owner.display_name').list.len(), 
                                descending=True)
                        .head(100).collect(streaming=True), 
                        column_config={"song_url": st.column_config.LinkColumn()}
                        )
    
    
    
                st.markdown(f"#### Most common songs to play before _{song_input}_:")
        
                st.dataframe(df
                        .select('song_number', 'track.name', 'playlist_name', 'track.id', 'song_url', 'owner.display_name', 'track.artists.name')
                        .unique()
                        .sort('playlist_name', 'song_number')
                        .with_columns(pair1 = pl.when(pl.col('song_number').shift(-1) > pl.col('song_number'))
                                                .then(pl.concat_str(pl.col('track.name'), pl.lit(': '), pl.col('track.id'), pl.lit(' --- '),
                                                                        pl.col('track.name').shift(-1), pl.lit(': '), pl.col('track.id').shift(-1),
                                                                        )),
                                        pair2 = pl.when(pl.col('song_number').shift(1) < pl.col('song_number'))
                                                .then(pl.concat_str(pl.col('track.name').shift(-1), pl.lit(': '), pl.col('track.id').shift(1), pl.lit(' --- '),
                                                                        pl.col('track.name'), pl.lit(': '), pl.col('track.id'),
                                                                        )),
                                        )
                        .with_columns(pair = pl.concat_list('pair1', 'pair2'))
                        .explode('pair')
                        .select('pair', 'playlist_name', 'owner.display_name', 'track.artists.name', 'track.name', 'song_url',
                                )
                        .drop_nulls()
                        .unique()
                        .with_columns(pl.col('pair').str.split(' --- ').list.sort().list.join(' --- '))
                        .group_by('pair')
                        .agg(pl.n_unique('playlist_name').alias('times_played_together'), 'playlist_name', 
                        'owner.display_name', 'track.artists.name', 'track.name', 'song_url')
                        .with_columns(pl.col('playlist_name').list.unique(),
                                        pl.col('owner.display_name').list.unique())
                        .filter(~pl.col('playlist_name').list.join(', ').str.contains_any(['The Maine', 'delete', 'SPOTIFY']),
                                pl.col('times_played_together').gt(1),
                                )
                        .filter(pl.col('pair').str.split(' --- ').list.get(1, null_on_oob=True).str.to_lowercase().str.contains(song_input_prepped),
                                pl.col('track.artists.name').list.join(', ').str.to_lowercase().str.contains(artist_name_input))
                        .with_columns(pl.col('pair').str.split(' --- '))
                        .sort('times_played_together',
                                pl.col('owner.display_name').list.len(), 
                                descending=True)
                        .head(100).collect(streaming=True), 
                        column_config={"song_url": st.column_config.LinkColumn()}
                        )
        st.markdown(f"#### ")














lyrics_toggle = st.toggle("📋 Search lyrics")
if lyrics_toggle:
                
        st.write(f"from {df_lyrics.select('artist', 'song').unique().collect(streaming=True).shape[0]:,} songs")
        lyrics_col1, lyrics_col2 = st.columns(2)
        with lyrics_col1:
                song_input = st.text_input("Song:")
                lyrics_input = [i.strip() for i in st.text_input("Lyrics (comma-separated):").split(',')]
                
        with lyrics_col2:
                artist_input = st.text_input("Artist:")

        st.dataframe(df_lyrics
        .join(df.select('song_url', 
                        song = pl.col('track.name'), 
                        artist = pl.col('track.artists.name')).unique(), 
                how='left', on=['song', 'artist'])
         .filter(pl.col('lyrics').str.contains_any(lyrics_input, ascii_case_insensitive=True),
                 pl.col('song').str.contains_any([song_input], ascii_case_insensitive=True),
                 pl.col('artist').str.contains_any([artist_input], ascii_case_insensitive=True),
                 )
         .with_columns(matched_lyrics = pl.col('lyrics')
                                        .str.extract_many(lyrics_input, ascii_case_insensitive=True)
                                        .list.eval(pl.element().str.to_lowercase())
                                        .list.unique(),
                       )
         .sort(pl.col('matched_lyrics').list.len(), descending=True)
         .group_by(pl.all().exclude('song_url')) #otherwise there will be multiple rows for each song variation
         .agg('song_url')
         .with_columns(pl.col('song_url').list.get(0)) #otherwise multiple urls will be smashed together
         .head(100)
         .collect(streaming=True), 
                 column_config={"song_url": st.column_config.LinkColumn()}
         )











faq_toggle = st.toggle("FAQ")
if faq_toggle:
st.markdown("""
### Westie Music Database FAQ

#### How can I help?
* Make lots of playlists with descriptive names! The more the better!
* Add "WCS" to your playlist name
* Add "yyyy-mm-dd" date (or variation) when you played the DJ set for a social
* Let me know the country of a user - helps our geographic insights!
* DJ's: Send me your VirtualDJ backup database file (it only includes the metadata, not the actual song files)

#### What can the Westie Music Database tell me?
* Top 1000 songs
* Event sets
* Most popular songs and playlists for:
	* Late-night
	* Competitions
	* Beginners
	* BPM-specific
	* Era's (80's, 90's, etc)
	* Holidays
	* Particular country (Germany)
* Comparing 2 DJ's music
* Songs unique to a particular DJ
* Comparing Country's music
* Songs unique to a country
* Top Songs per geographic region/country
* Songs only played in a
* Finding songs by lyrics
* Most popular songs played together

#### Where does the data come from?
- I find westies on Spotify, and use Spotify's API to grab all their public playlists.
- Currently trying to incorporate DJ data from VirtualDJ

#### Doesn't that mean there's some non-WCS music?
* Correct, not all music is WCS specific, but I filter out the bulk of it (Tango/Salsa/Etc.), and the music that's left rises to the top due to the amount of westies adding it to their playlists. Eg. If we all listen to non-westible show tunes, those songs might rise to the top, but we also have the # of playlists to sort by - Chunks, might appear in multiple playlists per spotify profile, but Defying Gravity would be in fewer.

#### I'm not a DJ and don't have a lot of playlists, can I be included?/why am I included?
* Please click the feedback form link and comment your profile link and location so I can include you! 
* The wonderful thing about aggregation on this scale is that even your 1 or 2 wcs playlists will still contribute to 

#### Artists are kinda messed up
* Yes, they're a pain, I'll handle it eventually, right now I'm ignoring it.

#### It broke ☹️
* Yes, there's a lot of processing involved (on 500MB+ with a 1GB machine 😬), and it occasionally blows up, I'm trying to alleviate it. It requires a manual reboot - so if you're working on something critical, ping me so I can restart it (whatsapp/fb)

#### Errors:
* Please report any errors you notice, or anything that doesn't make sense and I'll try to get to it!

#### Things to consider:
* Since the majority of data is based on user adding songs to their own playlists, user-generated vs DJ-generated, the playlists may not reflect actual played sets (except when specified). The benefit, while I work on rounding up DJ's not on Spotify, is that we get to see the ground truth of what users actually enjoy (such as songs missed by the GSDJ Top 10 lists).
            """)




st.markdown("#### ")
st.link_button('Add your info!', 
                   url='https://docs.google.com/spreadsheets/d/1zP8LYR9s33vzCGAv90N1tQfQ4JbNZgorvUNnvh1PeJY/edit?usp=sharing')
st.link_button('Find a WCS class near you!',
               url='https://www.affinityswing.com/classes')
st.link_button('Westie App Events Calendar',
               'https://westie-app.dance/calendar')
st.link_button('Weekenders Events Calendar',
               'https://weekenders.dance/')
st.link_button('Leave feedback/suggestions!/Report issues/bugs', 
                   url='https://forms.gle/19mALUpmM9Z5XCA28')

