from flask import json, make_response, current_app


class _Response(object):
    """Base webhook response to be returned to Dialogflow"""

    def __init__(self, speech):

        self._speech = speech
        self._integrations = current_app.config.get("INTEGRATIONS", [])
        self._messages = [{"text": {"text": [speech]}}]

        self._response = {
            "fulfillmentText": speech,
            "fulfillmentMessages": self._messages,
            "payload": {
                "google": {  # TODO: may be depreciated
                    "expect_user_response": True,
                    "is_ssml": True,
                    "permissions_request": None,
                }
            },
            "outputContexts": [],
            "source": "webhook",
            "followupEventInput": None,  # TODO
        }

        if "ACTIONS_ON_GOOGLE" in self._integrations:
            self._integrate_with_actions(speech)

    def _integrate_with_actions(self, speech=None):
        self._messages.append(
            {
                "platform": "ACTIONS_ON_GOOGLE",
                "simpleResponses": {"simpleResponses": [{"textToSpeech": speech}]},
            }
        )

    def _include_contexts(self):
        from flask_assistant import core

        for context in core.context_manager.active:
            self._response["outputContexts"].append(context.serialize)

    def render_response(self):
        from flask_assistant import core

        self._include_contexts()
        core._dbgdump(self._response)
        resp = json.dumps(self._response, indent=4)
        resp = make_response(resp)
        resp.headers["Content-Type"] = "application/json"

        return resp

    def suggest(self, replies):
        """Use suggestion chips to hint at responses to continue or pivot the conversation"""
        chips = []
        for r in replies:
            chips.append({"title": r})

        # NOTE: both of these formats work in the dialogflow console,
        # but only the first (suggestions) appears in actual Google Assistant

        # native chips for GA
        self._messages.append(
            {"platform": "ACTIONS_ON_GOOGLE", "suggestions": {"suggestions": chips}}
        )

        # quick replies for other platforms
        self._messages.append(
            {
                "platform": "ACTIONS_ON_GOOGLE",
                "quickReplies": {"title": None, "quickReplies": replies},
            }
        )

        return self

    def link_out(self, name, url):
        """Presents a chip similar to suggestion, but instead links to a url"""
        self._messages.append(
            {
                "type": "link_out_chip",
                "platform": "google",
                "destinationName": name,
                "url": url,
            }
        )
        return self

    def card(
        self,
        text,
        title,
        img_url=None,
        img_alt=None,
        subtitle=None,
        link=None,
        link_title=None,
    ):

        card_payload = {"title": title, "subtitle": subtitle, "formattedText": text}

        if link and link_title:
            btn_payload = [{"title": link_title, "openUriAction": {"uri": link}}]
            card_payload["buttons"] = btn_payload

        if img_url:
            img_payload = {"imageUri": img_url, "accessibilityText": img_alt or img_url}
            card_payload["image"] = img_payload

        self._messages.append(
            {"platform": "ACTIONS_ON_GOOGLE", "basicCard": card_payload}
        )

        return self

    def build_list(self, title=None, items=None):
        """Presents the user with a vertical list of multiple items.

        Allows the user to select a single item.
        Selection generates a user query containing the title of the list item

        *Note* Returns a completely new object,
        and does not modify the existing response object
        Therefore, to add items, must be assigned to new variable
        or call the method directly after initializing list

        example usage:

            simple = ask('I speak this text')
            mylist = simple.build_list('List Title')
            mylist.add_item('Item1', 'key1')
            mylist.add_item('Item2', 'key2')

            return mylist

        Arguments:
            title {str} -- Title displayed at top of list card

        Returns:
            _ListSelector -- [_Response object exposing the add_item method]

        """

        list_card = _ListSelector(self._speech, title, items)
        return list_card

    def build_carousel(self, items=None):
        carousel = _CarouselCard(self._speech, items)
        return carousel


def build_item(
    title, key=None, synonyms=None, description=None, img_url=None, alt_text=None
):
    """Builds an item that may be added to List or Carousel"""
    item = {
        "optionInfo": {"key": key or title, "synonyms": synonyms or []},
        "title": title,
        "description": description,
        "image": {
            "url": img_url or "",
            "accessibilityText": alt_text or "{} img".format(title),
        },
    }
    return item


class _CardWithItems(_Response):
    """Base class for Lists and Carousels to inherit from.

       Provides the meth:add_item method.
    """

    def __init__(self, speech, items=None):
        super(_CardWithItems, self).__init__(speech)
        self._items = items or list()
        self._add_message()  # possibly call this later?

    def _add_message(self):
        raise NotImplementedError

    def add_item(self, title, key, synonyms=None, description=None, img_url=None):
        """Adds item to a list or carousel card.

        A list must contain at least 2 items, each requiring a title and object key.

        Arguments:
            title {str} -- Name of the item object
            key {str} -- Key refering to the item.
                        This string will be used to send a query to your app if selected

        Keyword Arguments:
            synonyms {list} -- Words and phrases the user may send to select the item
                              (default: {None})
            description {str} -- A description of the item (default: {None})
            img_url {str} -- URL of the image to represent the item (default: {None})
        """
        item = build_item(title, key, synonyms, description, img_url)
        self._items.append(item)
        return self

    def include_items(self, *item_objects):
        if not isinstance(item_objects, list):
            item_objects = list(item_objects)
        self._items.extend(item_objects)

        return self


class _ListSelector(_CardWithItems):
    """Subclass of basic _Response to provide an instance capable of adding items."""

    def __init__(self, speech, title=None, items=None):
        self._title = title

        super(_ListSelector, self).__init__(speech, items)

    def _add_message(self):
        self._response["messages"].append(
            {
                "type": "list_card",
                "platform": "google",
                "title": self._title,
                "items": self._items,
            }
        )


class _CarouselCard(_CardWithItems):
    """Subclass of _CardWithItems used to build Carousel cards."""

    def __init__(self, speech, items=None):
        super(_CarouselCard, self).__init__(speech, items)

    def _add_message(self):

        self._response["messages"].append(
            {"type": "carousel_card", "platform": "google", "items": self._items}
        )


class tell(_Response):
    def __init__(self, speech):
        super(tell, self).__init__(speech)
        self._response["payload"]["google"]["expect_user_response"] = False


class ask(_Response):
    def __init__(self, speech):
        """Returns a response to the user and keeps the current session alive.
        Expects a response from the user.

        Arguments:
            speech {str} --  Text to be pronounced to the user / shown on the screen
        """
        super(ask, self).__init__(speech)
        self._response["payload"]["google"]["expect_user_response"] = True

    def reprompt(self, prompt):
        self._response["payload"]["google"]["no_input_prompts"] = [
            {"text_to_speech": prompt}
        ]

        return self


class event(_Response):
    """Triggers an event to invoke it's respective intent.

    When an event is triggered, speech, displayText and services' data will be ignored.
    """

    def __init__(self, event_name, **kwargs):
        super(event, self).__init__(speech=None)

        self._response["followupEvent"] = {"name": event_name, "parameters": kwargs}


class permission(_Response):
    """Returns a permission request to the user.

    Arguments:
        permissions {list} -- list of permissions to request for eg. ['DEVICE_PRECISE_LOCATION']
        context {str} -- Text explaining the reason/value for the requested permission
    """

    def __init__(self, permissions, context=None):
        super(permission, self).__init__(speech=None)
        self._messages[:] = []
        self._response["payload"]["google"]["systemIntent"] = {
            "intent": "actions.intent.PERMISSION",
            "data": {
                "@type": "type.googleapis.com/google.actions.v2.PermissionValueSpec",
                "optContext": context,
                "permissions": permissions,
            },
        }
